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
async def test_list_documents_query_count_is_constant(
    client: AsyncClient, db_session: AsyncSession, owner_id: uuid.UUID
):
    service = DocumentService(db_session)
    for i in range(12):
        doc = await service.create(
            DocumentCreate(title=f"Doc {i}", content="v1", owner_id=owner_id)
        )
        for v in range(2, 8):
            await service.update(
                doc.id, DocumentUpdate(title=f"Doc {i}", content=f"v{v}")
            )

    counts = {}
    for size in (1, 5, 12):
        resp = await client.get(
            "/api/v1/documents/", params={"owner_id": str(owner_id), "size": size}
        )
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == size
        counts[size] = int(resp.headers["X-DB-Queries"])

    assert len(set(counts.values())) == 1, counts
    assert counts[12] <= 5, counts
