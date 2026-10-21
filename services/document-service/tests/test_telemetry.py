"""The service reports how much database work each request cost."""

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_reports_query_count(client: AsyncClient, owner_id: uuid.UUID):
    for i in range(3):
        await client.post(
            "/api/v1/documents/",
            json={"title": f"Doc {i}", "content": "", "owner_id": str(owner_id)},
        )
    resp = await client.get("/api/v1/documents/", params={"owner_id": str(owner_id)})
    assert resp.status_code == 200
    assert int(resp.headers["X-DB-Queries"]) >= 2


@pytest.mark.asyncio
async def test_metrics_expose_query_fanout(client: AsyncClient, owner_id: uuid.UUID):
    await client.get("/api/v1/documents/", params={"owner_id": str(owner_id)})
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "otterworks_db_queries_per_request_bucket" in resp.text
    assert 'handler="/api/v1/documents/"' in resp.text
    assert "http_request_duration_seconds_bucket" in resp.text


@pytest.mark.asyncio
async def test_list_query_count_is_constant_in_page_size(
    client: AsyncClient, owner_id: uuid.UUID
):
    async def list_queries(n_docs: int) -> int:
        resp = await client.get(
            "/api/v1/documents/", params={"owner_id": str(owner_id), "size": n_docs}
        )
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == n_docs
        return int(resp.headers["X-DB-Queries"])

    for i in range(2):
        await client.post(
            "/api/v1/documents/",
            json={"title": f"Doc {i}", "content": "", "owner_id": str(owner_id)},
        )
    small = await list_queries(2)
    for i in range(2, 12):
        await client.post(
            "/api/v1/documents/",
            json={"title": f"Doc {i}", "content": "", "owner_id": str(owner_id)},
        )
    assert await list_queries(12) == small
