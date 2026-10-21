"""The service reports how much database work each request cost."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.document import DocumentCreate, DocumentUpdate
from app.services.document_service import DocumentService


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
    client: AsyncClient, db_session: AsyncSession, owner_id: uuid.UUID
):
    service = DocumentService(db_session)
    for i in range(25):
        doc = await service.create(
            DocumentCreate(title=f"Doc {i}", content="v1", owner_id=owner_id)
        )
        for v in range(2, 8):
            await service.update(doc.id, DocumentUpdate(title=f"Doc {i}", content=f"v{v}"))

    small = await client.get(
        "/api/v1/documents/", params={"owner_id": str(owner_id), "size": 2}
    )
    large = await client.get(
        "/api/v1/documents/", params={"owner_id": str(owner_id), "size": 25}
    )
    assert small.status_code == large.status_code == 200
    assert len(large.json()["items"]) == 25
    assert int(large.headers["X-DB-Queries"]) == int(small.headers["X-DB-Queries"])
    assert int(large.headers["X-DB-Queries"]) <= 5

    items, _ = await service.list_documents(owner_id=owner_id, size=25)
    for item in items:
        assert [v.version_number for v in item.recent_versions] == [7, 6, 5, 4, 3]
