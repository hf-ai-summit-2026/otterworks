"""Tests for SQSConsumer event normalization."""

from __future__ import annotations

import pytest

from app.services.sqs_consumer import SQSConsumer

normalize = SQSConsumer._normalize_event


class TestNormalizeDocumentServiceEvents:
    """snake_case event_type + payload (document-service)."""

    @pytest.mark.parametrize(
        ("event_type", "action"),
        [
            ("document_created", "index_document"),
            ("document_updated", "index_document"),
            ("document_deleted", "delete"),
            ("file_uploaded", "index_file"),
            ("file_trashed", "delete"),
        ],
    )
    def test_maps_event_type_to_action(self, event_type, action):
        payload = {"id": "doc-1", "title": "T"}
        result = normalize({"event_type": event_type, "payload": payload})
        assert result == {"action": action, "data": payload}

    def test_unknown_event_type_passes_through_as_action(self):
        result = normalize({"event_type": "document_shared", "payload": {"id": "d"}})
        assert result == {"action": "document_shared", "data": {"id": "d"}}


class TestNormalizeFileServiceEvents:
    """camelCase flat eventType events (file-service)."""

    def test_upload_maps_fields_to_snake_case(self):
        body = {
            "eventType": "file_uploaded",
            "fileId": "f-1",
            "ownerId": "u-1",
            "folderId": "fo-1",
            "name": "report.pdf",
            "mimeType": "application/pdf",
            "sizeBytes": 42,
            "timestamp": "2024-01-01T00:00:00Z",
        }
        assert normalize(body) == {
            "action": "index_file",
            "data": {
                "id": "f-1",
                "name": "report.pdf",
                "mime_type": "application/pdf",
                "owner_id": "u-1",
                "folder_id": "fo-1",
                "size": 42,
                "tags": [],
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            },
        }

    def test_accepts_shared_schema_file_name(self):
        body = {"eventType": "file_uploaded", "fileId": "f-1", "fileName": "a.txt"}
        assert normalize(body)["data"]["name"] == "a.txt"

    @pytest.mark.parametrize("event_type", ["file_deleted", "file_trashed"])
    def test_delete_events(self, event_type):
        body = {"eventType": event_type, "fileId": "f-1", "deletedBy": "u-1"}
        assert normalize(body) == {"action": "delete", "data": {"type": "file", "id": "f-1"}}

    @pytest.mark.parametrize("event_type", ["file_shared", "file_moved", "document_created"])
    def test_non_indexable_events_pass_through(self, event_type):
        body = {"eventType": event_type, "fileId": "f-1"}
        assert normalize(body) is body


def test_indexer_format_passes_through():
    body = {"action": "index_document", "data": {"id": "d"}}
    assert normalize(body) is body
