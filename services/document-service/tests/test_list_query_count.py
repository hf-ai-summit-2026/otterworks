"""GET /api/v1/documents/ costs a fixed number of SQL statements, whatever the page size."""

import uuid
from collections.abc import Iterator

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentVersion
from app.services.document_service import DocumentService
RECENT_VERSIONS_LIMIT = 5
from tests.conftest import engine

# count, page, selectin versions, selectin comments, batched recent versions
MAX_LIST_STATEMENTS = 5
VERSIONS_PER_DOCUMENT = RECENT_VERSIONS_LIMIT + 3


class StatementCounter:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def __call__(self, conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        self.statements.append(statement)


@pytest.fixture
def statements() -> Iterator[StatementCounter]:
    counter = StatementCounter()
    event.listen(engine.sync_engine, "before_cursor_execute", counter)
    yield counter
    event.remove(engine.sync_engine, "before_cursor_execute", counter)


async def _seed(db: AsyncSession, owner_id: uuid.UUID, documents: int) -> None:
    for i in range(documents):
        doc = Document(title=f"Doc {i}", content="", owner_id=owner_id, version=1)
        db.add(doc)
        await db.flush()
        for n in range(1, VERSIONS_PER_DOCUMENT + 1):
            db.add(
                DocumentVersion(
                    document_id=doc.id,
                    version_number=n,
                    title=f"Doc {i} v{n}",
                    content="",
                    created_by=owner_id,
                )
            )
    await db.commit()
    db.expunge_all()


async def _list_statement_count(
    client: AsyncClient, statements: StatementCounter, owner_id: uuid.UUID, size: int
) -> int:
    statements.statements.clear()
    resp = await client.get(
        "/api/v1/documents/", params={"owner_id": str(owner_id), "page": 1, "size": size}
    )
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == size
    assert int(resp.headers["X-DB-Queries"]) == len(statements.statements)
    return len(statements.statements)


@pytest.mark.asyncio
async def test_list_statement_count_is_constant_in_page_size(
    client: AsyncClient,
    db_session: AsyncSession,
    statements: StatementCounter,
    owner_id: uuid.UUID,
):
    await _seed(db_session, owner_id, documents=40)

    small = await _list_statement_count(client, statements, owner_id, size=2)
    db_session.expunge_all()
    large = await _list_statement_count(client, statements, owner_id, size=40)

    assert small == large
    assert large <= MAX_LIST_STATEMENTS
    version_selects = [
        s for s in statements.statements if "FROM document_versions" in s and "IN (" in s
    ]
    assert len(version_selects) == 2  # selectin `versions` + batched recent versions


@pytest.mark.asyncio
async def test_list_attaches_newest_versions_per_document(
    db_session: AsyncSession, owner_id: uuid.UUID
):
    await _seed(db_session, owner_id, documents=3)
    service = DocumentService(db_session)

    documents, total = await service.list_documents(owner_id=owner_id)

    assert total == 3
    expected = list(
        range(VERSIONS_PER_DOCUMENT, VERSIONS_PER_DOCUMENT - RECENT_VERSIONS_LIMIT, -1)
    )
    for doc in documents:
        assert [v.version_number for v in doc.recent_versions] == expected
        assert all(v.document_id == doc.id for v in doc.recent_versions)
