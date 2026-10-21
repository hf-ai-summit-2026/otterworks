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
    async def list_query_count(docs: int) -> int:
        owner = str(uuid.uuid4())
        for i in range(docs):
            created = await client.post(
                "/api/v1/documents/",
                json={"title": f"Doc {i}", "content": "v1", "owner_id": owner},
            )
            for v in range(6):
                await client.patch(
                    f"/api/v1/documents/{created.json()['id']}",
                    json={"content": f"v{v + 2}"},
                )
        resp = await client.get(
            "/api/v1/documents/", params={"owner_id": owner, "size": 100}
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == docs
        return int(resp.headers["X-DB-Queries"])

    small, large = await list_query_count(2), await list_query_count(15)
    assert small == large
