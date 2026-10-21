"""Tests for the Indexer service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from app.config import MeiliSearchConfig
from app.services.indexer import Indexer
from app.services.meilisearch_client import MeiliSearchService


@pytest.fixture()
def mock_ms_service() -> MeiliSearchService:
    """Create a MeiliSearchService with mocked client."""
    with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
        mock_client = MagicMock()

        mock_task = MagicMock()
        mock_task.task_uid = 1
        mock_task_result = MagicMock()
        mock_task_result.status = "succeeded"
        mock_client.wait_for_task.return_value = mock_task_result

        mock_index = MagicMock()
        mock_index.add_documents.return_value = mock_task
        mock_index.delete_document.return_value = mock_task
        mock_index.get_document.return_value = {"id": "doc-1"}
        mock_client.index.return_value = mock_index

        mock_client.create_index.return_value = mock_task
        mock_client.delete_index.return_value = mock_task
        mock_client.get_index.side_effect = None
        mock_client.health.return_value = {"status": "available"}

        mock_cls.return_value = mock_client
        service = MeiliSearchService(MeiliSearchConfig(
            documents_index="test-docs",
            files_index="test-files",
        ))
        yield service


@pytest.fixture()
def indexer(mock_ms_service: MeiliSearchService) -> Indexer:
    return Indexer(mock_ms_service)


class TestIndexer:
    """Tests for Indexer logic."""

    def test_index_document_success(self, indexer: Indexer):
        result = indexer.index_document({
            "id": "doc-1",
            "title": "Test Doc",
            "content": "Hello world",
            "owner_id": "user-1",
        })
        assert result["status"] == "indexed"
        assert result["type"] == "document"

    def test_index_document_missing_id(self, indexer: Indexer):
        with pytest.raises(ValueError, match="id"):
            indexer.index_document({"title": "No ID"})

    def test_index_document_missing_title(self, indexer: Indexer):
        with pytest.raises(ValueError, match="title"):
            indexer.index_document({"id": "doc-1"})

    def test_index_file_success(self, indexer: Indexer):
        result = indexer.index_file({
            "id": "file-1",
            "name": "report.pdf",
            "mime_type": "application/pdf",
            "owner_id": "user-1",
        })
        assert result["status"] == "indexed"
        assert result["type"] == "file"

    def test_index_file_missing_id(self, indexer: Indexer):
        with pytest.raises(ValueError, match="id"):
            indexer.index_file({"name": "report.pdf"})

    def test_index_file_missing_name(self, indexer: Indexer):
        with pytest.raises(ValueError, match="name"):
            indexer.index_file({"id": "file-1"})

    def test_remove_document(self, indexer: Indexer):
        result = indexer.remove("document", "doc-1")
        assert result["status"] == "deleted"
        assert result["type"] == "document"

    def test_remove_invalid_type(self, indexer: Indexer):
        with pytest.raises(ValueError, match="Invalid type"):
            indexer.remove("invalid", "id-1")

    def test_process_event_index_document(self, indexer: Indexer):
        result = indexer.process_event({
            "action": "index_document",
            "data": {"id": "doc-1", "title": "Test"},
        })
        assert result is not None
        assert result["status"] == "indexed"

    def test_process_event_index_file(self, indexer: Indexer):
        result = indexer.process_event({
            "action": "index_file",
            "data": {"id": "file-1", "name": "test.pdf"},
        })
        assert result is not None
        assert result["status"] == "indexed"

    def test_process_event_delete(self, indexer: Indexer):
        result = indexer.process_event({
            "action": "delete",
            "data": {"id": "doc-1", "type": "document"},
        })
        assert result is not None
        assert result["status"] == "deleted"

    def test_process_event_unknown_action(self, indexer: Indexer):
        result = indexer.process_event({"action": "unknown", "data": {}})
        assert result is None


def _response(status: int, payload: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload or {}
    return resp


class TestReindexFetch:
    def test_documents_paginate_until_empty_page(self):
        pages = [
            _response(200, {"documents": [{"id": "d1", "title": "One", "owner_id": "u1"}]}),
            _response(200, {"items": [{"id": "d2", "title": "Two"}]}),
            _response(200, {"documents": []}),
        ]
        with patch("app.services.indexer.requests.get", side_effect=pages) as mock_get:
            docs = Indexer._fetch_all_documents()
        assert [d["id"] for d in docs] == ["d1", "d2"]
        assert docs[0] == {
            "id": "d1",
            "title": "One",
            "content": "",
            "owner_id": "u1",
            "tags": [],
            "created_at": None,
            "updated_at": None,
            "type": "document",
        }
        assert [c.kwargs["params"]["page"] for c in mock_get.call_args_list] == [1, 2, 3]
        assert mock_get.call_args.args[0] == "http://document-service:8083/api/v1/documents/"

    def test_files_accept_camel_case_fields(self):
        pages = [
            _response(200, {"data": [{
                "id": "f1",
                "name": "a.pdf",
                "mimeType": "application/pdf",
                "ownerId": "u1",
                "folderId": "fold",
                "sizeBytes": 7,
                "createdAt": "c",
                "updatedAt": "u",
            }]}),
            _response(200, {}),
        ]
        with patch("app.services.indexer.requests.get", side_effect=pages) as mock_get:
            files = Indexer._fetch_all_files()
        assert files == [{
            "id": "f1",
            "name": "a.pdf",
            "mime_type": "application/pdf",
            "owner_id": "u1",
            "folder_id": "fold",
            "tags": [],
            "size": 7,
            "created_at": "c",
            "updated_at": "u",
            "type": "file",
        }]
        assert mock_get.call_args.args[0] == "http://file-service:8082/api/v1/files"

    def test_non_200_stops_fetch(self):
        with patch("app.services.indexer.requests.get", return_value=_response(503)):
            assert Indexer._fetch_all_files() == []

    def test_request_error_stops_fetch(self):
        pages = [
            _response(200, {"files": [{"id": "f1", "name": "a"}]}),
            requests.ConnectionError("down"),
        ]
        with patch("app.services.indexer.requests.get", side_effect=pages):
            files = Indexer._fetch_all_files()
        assert [f["id"] for f in files] == ["f1"]

    def test_reindex_passes_fetched_data(self, indexer: Indexer):
        with (
            patch.object(Indexer, "_fetch_all_documents", return_value=[{"id": "d1"}]),
            patch.object(Indexer, "_fetch_all_files", return_value=[]),
        ):
            result = indexer.reindex()
        assert result["indexed_counts"] == {"documents": 1, "files": 0}
