"""Tests for search API endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class TestSearchEndpoint:
    """Tests for GET /api/v1/search/."""

    def test_search_requires_query(self, client):
        """Search without 'q' returns 400."""
        response = client.get("/api/v1/search/")
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_search_with_query(self, client, mock_meilisearch_client):
        """Search with a valid query returns results."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {
            "estimatedTotalHits": 1,
            "hits": [
                {
                    "id": "doc-1",
                    "title": "Test Document",
                    "content": "Some content here",
                    "type": "document",
                    "owner_id": "user-1",
                    "tags": ["test"],
                    "_formatted": {
                        "title": "Test Document",
                        "content": "Some <em>content</em> here",
                    },
                }
            ],
        }

        response = client.get("/api/v1/search/?q=test")
        assert response.status_code == 200
        data = response.get_json()
        assert data["total"] >= 1
        assert len(data["results"]) >= 1
        assert data["query"] == "test"

    def test_search_with_type_filter(self, client, mock_meilisearch_client):
        """Search with type filter."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {
            "estimatedTotalHits": 0,
            "hits": [],
        }

        response = client.get("/api/v1/search/?q=test&type=file")
        assert response.status_code == 200

    def test_search_pagination(self, client, mock_meilisearch_client):
        """Search with pagination params."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {
            "estimatedTotalHits": 0,
            "hits": [],
        }

        response = client.get("/api/v1/search/?q=test&page=2&size=10")
        assert response.status_code == 200
        data = response.get_json()
        assert data["page"] == 2
        assert data["page_size"] == 10

    def test_search_invalid_page(self, client):
        """Search with non-numeric page returns 400."""
        response = client.get("/api/v1/search/?q=test&page=not-a-number")
        assert response.status_code == 400


class TestSuggestEndpoint:
    """Tests for GET /api/v1/search/suggest."""

    def test_suggest_short_query(self, client):
        """Suggest with query shorter than 2 chars returns empty."""
        response = client.get("/api/v1/search/suggest?q=a")
        assert response.status_code == 200
        data = response.get_json()
        assert data["suggestions"] == []

    def test_suggest_with_prefix(self, client, mock_meilisearch_client):
        """Suggest with valid prefix returns suggestions."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {
            "estimatedTotalHits": 2,
            "hits": [
                {"title": "Test Doc 1"},
                {"title": "Test Doc 2"},
            ],
        }

        response = client.get("/api/v1/search/suggest?q=te")
        assert response.status_code == 200
        data = response.get_json()
        assert len(data["suggestions"]) >= 1

    def test_suggest_empty_query(self, client):
        """Suggest with empty query returns empty list."""
        response = client.get("/api/v1/search/suggest?q=")
        assert response.status_code == 200
        data = response.get_json()
        assert data["suggestions"] == []


class TestAdvancedSearchEndpoint:
    """Tests for POST /api/v1/search/advanced."""

    def test_advanced_search_with_filters(self, client, mock_meilisearch_client):
        """Advanced search with multiple filters."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {
            "estimatedTotalHits": 0,
            "hits": [],
        }

        response = client.post(
            "/api/v1/search/advanced",
            json={
                "q": "report",
                "type": "document",
                "owner_id": "user-1",
                "tags": ["finance"],
                "date_from": "2024-01-01",
                "date_to": "2024-12-31",
                "page": 1,
                "size": 10,
            },
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "results" in data
        assert "total" in data

    def test_advanced_search_empty_body(self, client, mock_meilisearch_client):
        """Advanced search with empty body still works (match_all)."""
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = {
            "estimatedTotalHits": 0,
            "hits": [],
        }

        response = client.post("/api/v1/search/advanced", json={})
        assert response.status_code == 200


class TestAnalyticsEndpoint:
    """Tests for GET /api/v1/search/analytics."""

    def test_analytics_returns_data(self, client):
        """Analytics endpoint returns analytics data."""
        response = client.get("/api/v1/search/analytics")
        assert response.status_code == 200
        data = response.get_json()
        assert "popular_queries" in data
        assert "zero_result_queries" in data
        assert "total_searches" in data
        assert "avg_results_per_query" in data


class TestMultiIndexPagination:
    """search() and advanced_search() share the multi-index fan-out."""

    @staticmethod
    def _hits(prefix: str, n: int) -> dict:
        return {
            "estimatedTotalHits": n,
            "hits": [{"id": f"{prefix}-{i}", "title": f"{prefix}{i}", "name": f"{prefix}{i}"} for i in range(n)],
        }

    @pytest.mark.parametrize("method", ["search", "advanced_search"])
    def test_second_page_is_sliced_from_merged_hits(self, meilisearch_service, mock_meilisearch_client, method):
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.side_effect = [self._hits("doc", 4), self._hits("file", 4)]

        result = getattr(meilisearch_service, method)(query="q", page=2, page_size=3)

        assert [h.id for h in result.results] == ["doc-3", "file-0", "file-1"]
        assert result.total == 8
        for call in mock_index.search.call_args_list:
            assert call.args[1]["offset"] == 0
            assert call.args[1]["limit"] == 6

    @pytest.mark.parametrize("method", ["search", "advanced_search"])
    def test_single_index_paginates_server_side(self, meilisearch_service, mock_meilisearch_client, method):
        mock_index = mock_meilisearch_client.index.return_value
        mock_index.search.return_value = self._hits("file", 3)

        result = getattr(meilisearch_service, method)(query="q", doc_type="file", page=2, page_size=3)

        assert mock_index.search.call_count == 1
        params = mock_index.search.call_args.args[1]
        assert (params["offset"], params["limit"]) == (3, 3)
        assert len(result.results) == 3

    @pytest.mark.parametrize("method", ["search", "advanced_search"])
    def test_meilisearch_filter_error_raises_value_error(self, meilisearch_service, mock_meilisearch_client, method):
        import meilisearch

        mock_index = mock_meilisearch_client.index.return_value
        err = meilisearch.errors.MeilisearchApiError("bad filter", MagicMock(status_code=400, text="{}"))
        mock_index.search.side_effect = err

        with pytest.raises(ValueError, match="Invalid search filter"):
            getattr(meilisearch_service, method)(query="q")
