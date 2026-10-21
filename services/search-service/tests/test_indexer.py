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


def _response(status_code: int, body: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body or {}
    return resp


class TestReindexFetch:
    """Tests for the source-of-truth crawlers used by reindex."""

    @patch("app.services.indexer.requests.get")
    def test_fetch_all_documents_paginates_until_empty_page(self, mock_get: MagicMock):
        mock_get.side_effect = [
            _response(200, {"documents": [{"id": "d1", "title": "One"}]}),
            _response(200, {"items": [{"id": "d2", "title": "Two", "tags": ["x"]}]}),
            _response(200, {"documents": []}),
        ]

        docs = Indexer._fetch_all_documents()

        assert [d["id"] for d in docs] == ["d1", "d2"]
        assert docs[1]["tags"] == ["x"]
        assert all(d["type"] == "document" for d in docs)
        assert docs[0]["content"] == ""
        pages = [call.kwargs["params"]["page"] for call in mock_get.call_args_list]
        assert pages == [1, 2, 3]

    @patch("app.services.indexer.requests.get")
    def test_fetch_all_documents_stops_on_non_200(self, mock_get: MagicMock):
        mock_get.side_effect = [
            _response(200, {"data": [{"id": "d1", "title": "One"}]}),
            _response(503),
        ]

        docs = Indexer._fetch_all_documents()

        assert [d["id"] for d in docs] == ["d1"]
        assert mock_get.call_count == 2

    @patch("app.services.indexer.requests.get")
    def test_fetch_all_documents_returns_empty_on_request_error(self, mock_get: MagicMock):
        mock_get.side_effect = requests.ConnectionError("unreachable")

        assert Indexer._fetch_all_documents() == []

    @patch("app.services.indexer.requests.get")
    def test_fetch_all_files_normalizes_camel_case_fields(self, mock_get: MagicMock):
        mock_get.side_effect = [
            _response(200, {"files": [{
                "id": "f1",
                "name": "report.pdf",
                "mimeType": "application/pdf",
                "ownerId": "user-1",
                "folderId": "folder-1",
                "sizeBytes": 42,
                "createdAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-01-02T00:00:00Z",
            }]}),
            _response(200, {"files": []}),
        ]

        files = Indexer._fetch_all_files()

        assert files == [{
            "id": "f1",
            "name": "report.pdf",
            "mime_type": "application/pdf",
            "owner_id": "user-1",
            "folder_id": "folder-1",
            "tags": [],
            "size": 42,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
            "type": "file",
        }]

    @patch("app.services.indexer.requests.get")
    def test_fetch_all_files_prefers_snake_case_fields(self, mock_get: MagicMock):
        mock_get.side_effect = [
            _response(200, {"items": [{
                "id": "f1",
                "name": "a.txt",
                "mime_type": "text/plain",
                "mimeType": "ignored",
                "size": 7,
                "size_bytes": 99,
            }]}),
            _response(200, {}),
        ]

        files = Indexer._fetch_all_files()

        assert files[0]["mime_type"] == "text/plain"
        assert files[0]["size"] == 7

    @patch("app.services.indexer.requests.get")
    def test_fetch_all_files_returns_empty_on_request_error(self, mock_get: MagicMock):
        mock_get.side_effect = requests.Timeout("slow")

        assert Indexer._fetch_all_files() == []

    def test_reindex_passes_fetched_data_to_search(self, indexer: Indexer):
        docs = [{"id": "d1", "type": "document"}]
        files = [{"id": "f1", "type": "file"}]
        indexer.search = MagicMock()
        indexer.search.reindex.return_value = {"status": "reindexed"}

        with patch.object(Indexer, "_fetch_all_documents", return_value=docs), \
                patch.object(Indexer, "_fetch_all_files", return_value=files):
            result = indexer.reindex()

        indexer.search.reindex.assert_called_once_with(documents=docs, files=files)
        assert result == {"status": "reindexed"}
