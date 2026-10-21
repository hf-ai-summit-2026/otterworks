"""SQS event consumer for automatic search indexing."""

from __future__ import annotations

import json
import threading
import time
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from app.services.indexer import Indexer

logger = structlog.get_logger()

# Domain event type -> indexer action. Shared by every inbound event shape.
EVENT_ACTIONS: dict[str, str] = {
    "document_created": "index_document",
    "document_updated": "index_document",
    "document_deleted": "delete",
    "file_created": "index_file",
    "file_uploaded": "index_file",
    "file_updated": "index_file",
    "file_restored": "index_file",
    "file_deleted": "delete",
    "file_trashed": "delete",
}


def _file_event_to_index_data(body: dict[str, Any]) -> dict[str, Any]:
    """Map a camelCase file event to the snake_case fields the indexer expects.

    file-service emits ``name``; the shared schema names the field ``fileName``.
    """
    return {
        "id": body.get("fileId", ""),
        "name": body.get("name") or body.get("fileName", ""),
        "mime_type": body.get("mimeType", ""),
        "owner_id": body.get("ownerId", ""),
        "folder_id": body.get("folderId", ""),
        "size": body.get("sizeBytes", 0),
        "tags": body.get("tags", []),
        "created_at": body.get("timestamp"),
        "updated_at": body.get("timestamp"),
    }


class SQSConsumer:
    """Background thread SQS consumer for search-indexing queue events."""

    def __init__(
        self,
        indexer: Indexer,
        queue_url: str,
        region: str = "us-east-1",
        endpoint_url: str = "",
        max_messages: int = 10,
        wait_time_seconds: int = 20,
        visibility_timeout: int = 60,
    ) -> None:
        self.indexer = indexer
        self.queue_url = queue_url
        self.region = region
        self.endpoint_url = endpoint_url
        self.max_messages = max_messages
        self.wait_time_seconds = wait_time_seconds
        self.visibility_timeout = visibility_timeout
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the SQS consumer in a background daemon thread."""
        if not self.queue_url:
            logger.warning("sqs_consumer_skipped", reason="No SQS_QUEUE_URL configured")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="sqs-consumer"
        )
        self._thread.start()
        logger.info("sqs_consumer_started", queue_url=self.queue_url)

    def stop(self) -> None:
        """Stop the SQS consumer."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("sqs_consumer_stopped")

    def _create_sqs_client(self) -> Any:
        """Create the boto3 SQS client lazily."""
        import boto3

        kwargs: dict[str, Any] = {"region_name": self.region}
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        return boto3.client("sqs", **kwargs)

    def _poll_loop(self) -> None:
        """Main polling loop for SQS messages."""
        sqs = self._create_sqs_client()

        while self._running:
            try:
                response = sqs.receive_message(
                    QueueUrl=self.queue_url,
                    MaxNumberOfMessages=self.max_messages,
                    WaitTimeSeconds=self.wait_time_seconds,
                    VisibilityTimeout=self.visibility_timeout,
                )

                messages = response.get("Messages", [])
                for message in messages:
                    self._process_message(sqs, message)

            except Exception:
                logger.exception("sqs_consumer_error")
                time.sleep(5)

    @staticmethod
    def _normalize_event(body: dict[str, Any]) -> dict[str, Any]:
        """Normalize event payloads from different services into the indexer format.

        Handles:
        - snake_case ``event_type`` + nested ``payload`` (document-service)
        - camelCase flat ``eventType`` events (file-service; see
          ``shared/events/schemas/file-events.json``)
        - events already in indexer format (``action`` + ``data``), returned as-is
        """
        if "event_type" in body and "payload" in body:
            action = EVENT_ACTIONS.get(body["event_type"], body["event_type"])
            return {"action": action, "data": body["payload"]}

        if "eventType" in body:
            action = EVENT_ACTIONS.get(body["eventType"])
            # Events without file metadata (file_shared, file_moved, document
            # events on this shape) can't be indexed; pass them through so the
            # indexer logs them as unknown and they are acked.
            if action is None or action == "index_document":
                return body
            if action == "delete":
                return {"action": "delete", "data": {"type": "file", "id": body.get("fileId", "")}}
            return {"action": action, "data": _file_event_to_index_data(body)}

        return body

    def _process_message(self, sqs: Any, message: dict[str, Any]) -> None:
        """Process a single SQS message."""
        receipt_handle = message.get("ReceiptHandle", "")
        try:
            body = json.loads(message.get("Body", "{}"))

            # Handle SNS-wrapped messages
            if "Message" in body and "TopicArn" in body:
                body = json.loads(body["Message"])

            body = self._normalize_event(body)

            result = self.indexer.process_event(body)
            logger.info("sqs_message_processed", result=result)

            # Delete the message after successful processing
            sqs.delete_message(QueueUrl=self.queue_url, ReceiptHandle=receipt_handle)

        except json.JSONDecodeError:
            logger.error("sqs_message_invalid_json", message_id=message.get("MessageId"))
            sqs.delete_message(QueueUrl=self.queue_url, ReceiptHandle=receipt_handle)
        except ValueError:
            logger.error(
                "sqs_message_validation_failed", message_id=message.get("MessageId")
            )
            sqs.delete_message(QueueUrl=self.queue_url, ReceiptHandle=receipt_handle)
        except Exception:
            logger.exception(
                "sqs_message_processing_failed", message_id=message.get("MessageId")
            )
