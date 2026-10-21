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
async def test_list_query_count_does_not_grow_with_page_size(
    client: AsyncClient, owner_id: uuid.UUID
):
    async def create(n: int) -> None:
        for i in range(n):
            await client.post(
                "/api/v1/documents/",
                json={"title": f"Doc {i}", "content": "", "owner_id": str(owner_id)},
            )

    async def list_queries(expected_items: int) -> int:
        resp = await client.get(
            "/api/v1/documents/", params={"owner_id": str(owner_id), "size": 100}
        )
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == expected_items
        return int(resp.headers["X-DB-Queries"])

    await create(2)
    small = await list_queries(2)
    await create(10)
    large = await list_queries(12)
    assert small == large
    assert large <= 5
