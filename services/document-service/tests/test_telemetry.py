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


async def _list_query_count(
    client: AsyncClient, db_session: AsyncSession, owner_id: uuid.UUID, docs: int
) -> int:
    service = DocumentService(db_session)
    for i in range(docs):
        doc = await service.create(DocumentCreate(title=f"Doc {i}", content="", owner_id=owner_id))
        await service.update(doc.id, DocumentUpdate(title=f"Doc {i} v2", content="edited"))
    resp = await client.get("/api/v1/documents/", params={"owner_id": str(owner_id), "size": 100})
    assert resp.status_code == 200
    assert resp.json()["total"] == docs
    return int(resp.headers["X-DB-Queries"])


@pytest.mark.asyncio
async def test_list_query_count_is_constant_in_page_size(
    client: AsyncClient, db_session: AsyncSession
):
    small = await _list_query_count(client, db_session, uuid.uuid4(), 2)
    large = await _list_query_count(client, db_session, uuid.uuid4(), 25)
    assert large == small
    assert large <= 5
