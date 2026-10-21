"""Tests for MeiliSearchService query building, pagination and error mapping."""

from __future__ import annotations

from unittest.mock import MagicMock

import meilisearch
import pytest

from app.services.meilisearch_client import MeiliSearchService


def _api_error() -> meilisearch.errors.MeilisearchApiError:
    response = MagicMock()
    response.status_code = 400
    response.text = '{"message": "invalid filter", "code": "invalid_search_filter"}'
    return meilisearch.errors.MeilisearchApiError("invalid filter", response)


def _hits(prefix: str, count: int) -> list[dict]:
    return [{"id": f"{prefix}-{i}", "title": f"{prefix} {i}", "name": f"{prefix} {i}"} for i in range(count)]


@pytest.fixture()
def index(mock_meilisearch_client: MagicMock) -> MagicMock:
    return mock_meilisearch_client.index.return_value


class TestSearch:
    def test_filters_are_escaped_and_combined(self, meilisearch_service: MeiliSearchService, index):
        meilisearch_service.search("q", doc_type="document", owner_id='u"1\\x')
        _, params = index.search.call_args.args
        assert params["filter"] == 'type = "document" AND owner_id = "u\\"1\\\\x"'
        assert params["offset"] == 0
        assert params["limit"] == 20

    def test_no_filter_when_unscoped(self, meilisearch_service: MeiliSearchService, index):
        meilisearch_service.search("q")
        _, params = index.search.call_args.args
        assert "filter" not in params

    def test_single_index_uses_offset_pagination(self, meilisearch_service: MeiliSearchService, index):
        index.search.return_value = {"hits": _hits("d", 5), "estimatedTotalHits": 30}
        result = meilisearch_service.search("q", doc_type="file", page=3, page_size=5)
        _, params = index.search.call_args.args
        assert (params["offset"], params["limit"]) == (10, 5)
        assert index.search.call_count == 1
        assert [h.id for h in result.results] == [f"d-{i}" for i in range(5)]
        assert result.total == 30

    def test_multi_index_merges_and_slices(self, meilisearch_service: MeiliSearchService, index):
        index.search.side_effect = [
            {"hits": _hits("doc", 4), "estimatedTotalHits": 4},
            {"hits": _hits("file", 4), "estimatedTotalHits": 4},
        ]
        result = meilisearch_service.search("q", page=2, page_size=3)
        _, params = index.search.call_args.args
        assert (params["offset"], params["limit"]) == (0, 6)
        assert [h.id for h in result.results] == ["doc-3", "file-0", "file-1"]
        assert result.total == 8
        assert result.query == "q"

    def test_api_error_becomes_value_error(self, meilisearch_service: MeiliSearchService, index):
        index.search.side_effect = _api_error()
        with pytest.raises(ValueError, match="Invalid search filter"):
            meilisearch_service.search("q")


class TestAdvancedSearch:
    def test_all_filters(self, meilisearch_service: MeiliSearchService, index):
        meilisearch_service.advanced_search(
            query="report",
            doc_type="document",
            owner_id="user-1",
            tags=["a", "b"],
            date_from="2024-01-01",
            date_to="2024-12-31",
        )
        term, params = index.search.call_args.args
        assert term == "report"
        assert params["filter"] == (
            'type = "document" AND owner_id = "user-1" AND (tags = "a" OR tags = "b") '
            'AND created_at >= "2024-01-01" AND created_at <= "2024-12-31"'
        )

    def test_empty_query_reports_wildcard(self, meilisearch_service: MeiliSearchService, index):
        result = meilisearch_service.advanced_search()
        term, _ = index.search.call_args.args
        assert term == ""
        assert result.query == "*"

    def test_api_error_is_not_mapped(self, meilisearch_service: MeiliSearchService, index):
        index.search.side_effect = _api_error()
        with pytest.raises(meilisearch.errors.MeilisearchApiError):
            meilisearch_service.advanced_search(query="q")


class TestSearchApiErrorMapping:
    def test_search_invalid_filter_returns_400(self, client, mock_meilisearch_client):
        mock_meilisearch_client.index.return_value.search.side_effect = _api_error()
        response = client.get("/api/v1/search/?q=test")
        assert response.status_code == 400

    def test_advanced_search_backend_error_returns_500(self, client, mock_meilisearch_client):
        mock_meilisearch_client.index.return_value.search.side_effect = _api_error()
        response = client.post("/api/v1/search/advanced", json={"q": "test"})
        assert response.status_code == 500
        assert response.get_json() == {"error": "Advanced search failed"}
