"""The document list costs a constant number of SQL statements, whatever the page size."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentVersion
from app.services.document_service import DocumentService

VERSIONS_PER_DOCUMENT = 7
STATEMENTS_PER_LIST = 5


async def _seed(db: AsyncSession, owner_id: uuid.UUID, documents: int) -> None:
    for i in range(documents):
        doc = Document(
            title=f"Doc {i}", content="", owner_id=owner_id, version=VERSIONS_PER_DOCUMENT
        )
        db.add(doc)
        await db.flush()
        db.add_all(
            DocumentVersion(
                document_id=doc.id,
                version_number=n,
                title=doc.title,
                content="",
                created_by=owner_id,
            )
            for n in range(1, VERSIONS_PER_DOCUMENT + 1)
        )
    await db.commit()
    db.expunge_all()


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [1, 10, 50])
async def test_list_issues_constant_statements(
    client: AsyncClient, db_session: AsyncSession, owner_id: uuid.UUID, size: int
):
    await _seed(db_session, owner_id, 50)

    resp = await client.get("/api/v1/documents/", params={"owner_id": str(owner_id), "size": size})

    assert resp.status_code == 200
    assert len(resp.json()["items"]) == size
    assert int(resp.headers["X-DB-Queries"]) == STATEMENTS_PER_LIST


@pytest.mark.asyncio
async def test_list_attaches_five_most_recent_versions(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    await _seed(db_session, owner_id, 3)

    documents, _ = await DocumentService(db_session).list_documents(owner_id=owner_id)

    assert len(documents) == 3
    for doc in documents:
        assert [v.document_id for v in doc.recent_versions] == [doc.id] * 5
        assert [v.version_number for v in doc.recent_versions] == [7, 6, 5, 4, 3]
