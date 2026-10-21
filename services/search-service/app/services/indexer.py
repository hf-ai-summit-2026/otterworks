"""Document and file indexing logic."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import requests
import structlog

from app.services.meilisearch_client import MeiliSearchService

logger = structlog.get_logger()

DOCUMENT_SERVICE_URL = "http://document-service:8083"
FILE_SERVICE_URL = "http://file-service:8082"
FETCH_TIMEOUT = 30
PAGE_SIZE = 100


def _document_from_source(item: dict[str, Any]) -> dict[str, Any]:
    """Map a document-service listing item to a search index document."""
    return {
        "id": item.get("id", ""),
        "title": item.get("title", ""),
        "content": item.get("content", ""),
        "owner_id": item.get("owner_id", ""),
        "tags": item.get("tags", []),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "type": "document",
    }


def _file_from_source(item: dict[str, Any]) -> dict[str, Any]:
    """Map a file-service listing item (snake_case or camelCase) to a search index document."""
    return {
        "id": item.get("id", ""),
        "name": item.get("name", ""),
        "mime_type": item.get("mime_type", item.get("mimeType", "")),
        "owner_id": item.get("owner_id", item.get("ownerId", "")),
        "folder_id": item.get("folder_id", item.get("folderId", "")),
        "tags": item.get("tags", []),
        "size": item.get("size", item.get("size_bytes", item.get("sizeBytes", 0))),
        "created_at": item.get("created_at", item.get("createdAt")),
        "updated_at": item.get("updated_at", item.get("updatedAt")),
        "type": "file",
    }


class Indexer:
    """Handles document and file indexing into MeiliSearch."""

    def __init__(self, search_service: MeiliSearchService) -> None:
        self.search = search_service

    def index_document(self, payload: dict[str, Any]) -> dict[str, str]:
        """Validate and index a document.

        Expected payload fields:
            id, title, content, owner_id, tags, created_at, updated_at
        """
        if not payload.get("id"):
            raise ValueError("Document 'id' is required")
        if not payload.get("title"):
            raise ValueError("Document 'title' is required")

        document = {
            "id": payload["id"],
            "title": payload["title"],
            "content": payload.get("content", ""),
            "owner_id": payload.get("owner_id", ""),
            "tags": payload.get("tags", []),
            "created_at": payload.get("created_at"),
            "updated_at": payload.get("updated_at"),
        }

        self.search.index_document(document)
        logger.info("indexer_document_indexed", document_id=document["id"])
        return {"status": "indexed", "id": document["id"], "type": "document"}

    def index_file(self, payload: dict[str, Any]) -> dict[str, str]:
        """Validate and index a file.

        Expected payload fields:
            id, name, mime_type, owner_id, folder_id, tags, size, created_at
        """
        if not payload.get("id"):
            raise ValueError("File 'id' is required")
        if not payload.get("name"):
            raise ValueError("File 'name' is required")

        file_data = {
            "id": payload["id"],
            "name": payload["name"],
            "mime_type": payload.get("mime_type", ""),
            "owner_id": payload.get("owner_id", ""),
            "folder_id": payload.get("folder_id", ""),
            "tags": payload.get("tags", []),
            "size": payload.get("size", 0),
            "created_at": payload.get("created_at"),
            "updated_at": payload.get("updated_at"),
        }

        self.search.index_file(file_data)
        logger.info("indexer_file_indexed", file_id=file_data["id"])
        return {"status": "indexed", "id": file_data["id"], "type": "file"}

    def remove(self, doc_type: str, doc_id: str) -> dict[str, Any]:
        """Remove a document or file from the index."""
        if doc_type not in ("document", "file"):
            raise ValueError(f"Invalid type '{doc_type}'. Must be 'document' or 'file'.")

        deleted = self.search.delete_document(doc_type, doc_id)
        status = "deleted" if deleted else "not_found"
        logger.info("indexer_document_removed", doc_id=doc_id, doc_type=doc_type, status=status)
        return {"status": status, "id": doc_id, "type": doc_type}

    def reindex(self) -> dict[str, Any]:
        """Trigger a full reindex by crawling source-of-truth services.

        Fetches all documents from the document-service and all files
        from the file-service, then passes them to MeiliSearch for
        bulk re-indexing.  If a source service is unreachable the
        corresponding index is still cleared and recreated empty.
        """
        documents = self._fetch_all_documents()
        files = self._fetch_all_files()
        result = self.search.reindex(documents=documents, files=files)
        logger.info(
            "indexer_reindex_complete",
            documents=len(documents),
            files=len(files),
        )
        return result

    @staticmethod
    def _fetch_all_documents() -> list[dict[str, Any]]:
        """Paginate through the document-service to collect all documents."""
        return Indexer._fetch_paginated(
            url=f"{DOCUMENT_SERVICE_URL}/api/v1/documents/",
            collection_key="documents",
            to_index_doc=_document_from_source,
            log_prefix="reindex_document_fetch",
        )

    @staticmethod
    def _fetch_all_files() -> list[dict[str, Any]]:
        """Paginate through the file-service to collect all file metadata."""
        return Indexer._fetch_paginated(
            url=f"{FILE_SERVICE_URL}/api/v1/files",
            collection_key="files",
            to_index_doc=_file_from_source,
            log_prefix="reindex_file_fetch",
        )

    @staticmethod
    def _fetch_paginated(
        url: str,
        collection_key: str,
        to_index_doc: Callable[[dict[str, Any]], dict[str, Any]],
        log_prefix: str,
    ) -> list[dict[str, Any]]:
        """Collect every item from a paginated source-of-truth listing endpoint.

        Stops on the first empty page, non-200 response or request error.
        """
        collected: list[dict[str, Any]] = []
        page = 1
        while True:
            try:
                resp = requests.get(
                    url,
                    params={"page": page, "page_size": PAGE_SIZE},
                    timeout=FETCH_TIMEOUT,
                )
                if resp.status_code != 200:
                    logger.warning(f"{log_prefix}_failed", status=resp.status_code)
                    break
                data = resp.json()
                items = data.get(collection_key) or data.get("items") or data.get("data") or []
                if not items:
                    break
                collected.extend(to_index_doc(item) for item in items)
                page += 1
            except requests.RequestException:
                logger.exception(f"{log_prefix}_error")
                break
        return collected

    def process_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Process an SQS event message.

        Expected event format:
            {"action": "index_document"|"index_file"|"delete", "data": {...}}
        """
        action = event.get("action", "")
        data = event.get("data", {})

        if action == "index_document":
            return self.index_document(data)
        elif action == "index_file":
            return self.index_file(data)
        elif action == "delete":
            doc_type = data.get("type", "document")
            doc_id = data.get("id", "")
            return self.remove(doc_type, doc_id)
        else:
            logger.warning("indexer_unknown_action", action=action)
            return None
