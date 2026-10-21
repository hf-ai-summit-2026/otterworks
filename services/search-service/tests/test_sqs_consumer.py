"""Tests for the SQS consumer event normalization and message handling."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.sqs_consumer import EVENT_ACTIONS, FILE_EVENT_ACTIONS, SQSConsumer

QUEUE_URL = "http://localstack:4566/000000000000/otterworks-search-events"


@pytest.fixture()
def indexer() -> MagicMock:
    mock = MagicMock()
    mock.process_event.return_value = {"status": "indexed"}
    return mock


@pytest.fixture()
def consumer(indexer: MagicMock) -> SQSConsumer:
    return SQSConsumer(indexer=indexer, queue_url=QUEUE_URL)


def _message(body: object, raw: str | None = None) -> dict:
    return {
        "MessageId": "msg-1",
        "ReceiptHandle": "rh-1",
        "Body": raw if raw is not None else json.dumps(body),
    }


class TestActionMaps:
    def test_file_actions_are_subset_of_event_actions(self):
        for event_type, action in FILE_EVENT_ACTIONS.items():
            assert EVENT_ACTIONS[event_type] == action

    def test_document_actions(self):
        assert EVENT_ACTIONS["document_created"] == "index_document"
        assert EVENT_ACTIONS["document_updated"] == "index_document"
        assert EVENT_ACTIONS["document_deleted"] == "delete"

    @pytest.mark.parametrize("event_type", ["file_shared", "file_moved"])
    def test_metadata_less_file_events_not_mapped(self, event_type):
        assert event_type not in FILE_EVENT_ACTIONS


class TestNormalizeEvent:
    def test_snake_case_envelope(self):
        body = {"event_type": "document_updated", "payload": {"id": "doc-1"}}
        assert SQSConsumer._normalize_event(body) == {
            "action": "index_document",
            "data": {"id": "doc-1"},
        }

    def test_snake_case_unknown_event_passes_through_type(self):
        body = {"event_type": "document_shared", "payload": {"id": "doc-1"}}
        assert SQSConsumer._normalize_event(body)["action"] == "document_shared"

    def test_camel_case_file_upload(self):
        body = {
            "eventType": "file_uploaded",
            "fileId": "file-1",
            "name": "report.pdf",
            "mimeType": "application/pdf",
            "ownerId": "user-1",
            "folderId": "folder-1",
            "sizeBytes": 42,
            "timestamp": "2026-01-01T00:00:00Z",
        }
        assert SQSConsumer._normalize_event(body) == {
            "action": "index_file",
            "data": {
                "id": "file-1",
                "name": "report.pdf",
                "mime_type": "application/pdf",
                "owner_id": "user-1",
                "folder_id": "folder-1",
                "size": 42,
                "tags": [],
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
        }

    def test_camel_case_file_delete(self):
        body = {"eventType": "file_trashed", "fileId": "file-1"}
        assert SQSConsumer._normalize_event(body) == {
            "action": "delete",
            "data": {"type": "file", "id": "file-1"},
        }

    def test_camel_case_unmapped_event_returned_unchanged(self):
        body = {"eventType": "file_shared", "fileId": "file-1"}
        assert SQSConsumer._normalize_event(body) is body

    def test_indexer_format_passes_through(self):
        body = {"action": "index_document", "data": {"id": "doc-1"}}
        assert SQSConsumer._normalize_event(body) is body


class TestProcessMessage:
    def test_success_deletes_message(self, consumer, indexer):
        sqs = MagicMock()
        consumer._process_message(sqs, _message({"action": "index_document", "data": {"id": "d"}}))
        indexer.process_event.assert_called_once_with({"action": "index_document", "data": {"id": "d"}})
        sqs.delete_message.assert_called_once_with(QueueUrl=QUEUE_URL, ReceiptHandle="rh-1")

    def test_sns_wrapped_message_is_unwrapped(self, consumer, indexer):
        inner = {"event_type": "document_created", "payload": {"id": "doc-1"}}
        envelope = {"TopicArn": "arn:aws:sns:us-east-1:000000000000:t", "Message": json.dumps(inner)}
        sqs = MagicMock()
        consumer._process_message(sqs, _message(envelope))
        indexer.process_event.assert_called_once_with(
            {"action": "index_document", "data": {"id": "doc-1"}}
        )
        sqs.delete_message.assert_called_once()

    def test_invalid_json_is_dropped(self, consumer, indexer):
        sqs = MagicMock()
        consumer._process_message(sqs, _message(None, raw="{not json"))
        indexer.process_event.assert_not_called()
        sqs.delete_message.assert_called_once()

    def test_validation_error_is_dropped(self, consumer, indexer):
        indexer.process_event.side_effect = ValueError("Document 'id' is required")
        sqs = MagicMock()
        consumer._process_message(sqs, _message({"action": "index_document", "data": {}}))
        sqs.delete_message.assert_called_once()

    def test_unexpected_error_leaves_message_for_retry(self, consumer, indexer):
        indexer.process_event.side_effect = RuntimeError("meilisearch down")
        sqs = MagicMock()
        consumer._process_message(sqs, _message({"action": "index_document", "data": {"id": "d"}}))
        sqs.delete_message.assert_not_called()


class TestLifecycle:
    def test_start_without_queue_url_is_noop(self, indexer):
        consumer = SQSConsumer(indexer=indexer, queue_url="")
        consumer.start()
        assert consumer._thread is None
        assert consumer._running is False

    def test_create_client_passes_endpoint(self, indexer):
        consumer = SQSConsumer(
            indexer=indexer, queue_url=QUEUE_URL, region="eu-west-1", endpoint_url="http://ls:4566"
        )
        with patch("boto3.client") as mock_client:
            consumer._create_sqs_client()
        mock_client.assert_called_once_with(
            "sqs", region_name="eu-west-1", endpoint_url="http://ls:4566"
        )

    def test_create_client_without_endpoint(self, indexer):
        consumer = SQSConsumer(indexer=indexer, queue_url=QUEUE_URL)
        with patch("boto3.client") as mock_client:
            consumer._create_sqs_client()
        mock_client.assert_called_once_with("sqs", region_name="us-east-1")
