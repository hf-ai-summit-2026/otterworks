"""Tests for indexing API endpoints."""

from __future__ import annotations


class TestIndexDocumentEndpoint:
    """Tests for POST /api/v1/search/index/document."""

    def test_index_document_success(self, client, mock_meilisearch_client):
        """Index a valid document returns 201."""
        response = client.post(
            "/api/v1/search/index/document",
            json={
                "id": "doc-123",
                "title": "My Document",
                "content": "Document body text",
                "owner_id": "user-1",
                "tags": ["work"],
            },
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["status"] == "indexed"
        assert data["id"] == "doc-123"
        assert data["type"] == "document"

    def test_index_document_missing_body(self, client):
        """Index with empty body returns 400."""
        response = client.post(
            "/api/v1/search/index/document",
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_index_document_missing_id(self, client, mock_meilisearch_client):
        """Index document without id returns 400."""
        response = client.post(
            "/api/v1/search/index/document",
            json={"title": "No ID Doc"},
        )
        assert response.status_code == 400

    def test_index_document_missing_title(self, client, mock_meilisearch_client):
        """Index document without title returns 400."""
        response = client.post(
            "/api/v1/search/index/document",
            json={"id": "doc-no-title"},
        )
        assert response.status_code == 400


class TestIndexFileEndpoint:
    """Tests for POST /api/v1/search/index/file."""

    def test_index_file_success(self, client, mock_meilisearch_client):
        """Index a valid file returns 201."""
        response = client.post(
            "/api/v1/search/index/file",
            json={
                "id": "file-123",
                "name": "report.pdf",
                "mime_type": "application/pdf",
                "owner_id": "user-1",
                "folder_id": "folder-1",
                "tags": ["report"],
                "size": 1024,
            },
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["status"] == "indexed"
        assert data["id"] == "file-123"
        assert data["type"] == "file"

    def test_index_file_missing_name(self, client, mock_meilisearch_client):
        """Index file without name returns 400."""
        response = client.post(
            "/api/v1/search/index/file",
            json={"id": "file-no-name"},
        )
        assert response.status_code == 400


class TestDeleteFromIndexEndpoint:
    """Tests for DELETE /api/v1/search/index/{type}/{id}."""

    def test_delete_document(self, client, mock_meilisearch_client):
        """Delete a document from index returns 200."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.get_document.return_value = {"id": "doc-123"}
        response = client.delete("/api/v1/search/index/document/doc-123")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "deleted"

    def test_delete_invalid_type(self, client, mock_meilisearch_client):
        """Delete with invalid type returns 400."""
        response = client.delete("/api/v1/search/index/invalid/doc-123")
        assert response.status_code == 400


class TestReindexEndpoint:
    """Tests for POST /api/v1/search/reindex."""

    def test_reindex_success(self, client, mock_meilisearch_client):
        """Reindex returns 200."""
        response = client.post("/api/v1/search/reindex")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "reindexed"


class TestIndexErrorHandling:
    """Error mapping for the indexing endpoints."""

    def test_delete_not_found_returns_404(self, client, mock_meilisearch_client):
        import meilisearch

        response_obj = mock_meilisearch_client.index.return_value
        err_response = type("R", (), {"status_code": 404, "text": '{"message": "nope"}'})()
        response_obj.get_document.side_effect = meilisearch.errors.MeilisearchApiError("nope", err_response)
        response = client.delete("/api/v1/search/index/file/missing")
        assert response.status_code == 404
        assert response.get_json()["status"] == "not_found"

    def test_index_document_backend_failure_returns_500(self, client, mock_meilisearch_client):
        mock_meilisearch_client.index.return_value.add_documents.side_effect = RuntimeError("down")
        response = client.post("/api/v1/search/index/document", json={"id": "d", "title": "t"})
        assert response.status_code == 500
        assert response.get_json() == {"error": "Failed to index document"}

    def test_index_file_backend_failure_returns_500(self, client, mock_meilisearch_client):
        mock_meilisearch_client.index.return_value.add_documents.side_effect = RuntimeError("down")
        response = client.post("/api/v1/search/index/file", json={"id": "f", "name": "n"})
        assert response.status_code == 500
        assert response.get_json() == {"error": "Failed to index file"}

    def test_reindex_backend_failure_returns_500(self, client, mock_meilisearch_client):
        mock_meilisearch_client.delete_index.side_effect = None
        mock_meilisearch_client.index.return_value.update_searchable_attributes.side_effect = RuntimeError("x")
        response = client.post("/api/v1/search/reindex")
        assert response.status_code == 500
        assert response.get_json() == {"error": "Failed to reindex"}
