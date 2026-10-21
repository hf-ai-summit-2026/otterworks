"""Boot-time index creation is idempotent and covers the hot query paths."""

import pytest
from pymongo.asynchronous.database import AsyncDatabase

from app.db import mongo
from app.models.document import DOCUMENT_VERSIONS, DOCUMENTS


@pytest.mark.asyncio
async def test_ensure_indexes_is_idempotent(db_session: AsyncDatabase) -> None:
    first = await mongo.ensure_indexes(db_session)
    second = await mongo.ensure_indexes(db_session)
    assert first == second
    assert "documents_owner_live_updated" in first[DOCUMENTS]
    assert "versions_document_version" in first[DOCUMENT_VERSIONS]


@pytest.mark.asyncio
async def test_indexes_exist_in_collections(db_session: AsyncDatabase) -> None:
    info = await db_session[DOCUMENTS].index_information()
    assert set(info["documents_owner_live_updated"]["key"]) == {
        ("owner_id", 1),
        ("is_deleted", 1),
        ("is_template", 1),
        ("updated_at", -1),
    }
    versions = await db_session[DOCUMENT_VERSIONS].index_information()
    assert versions["versions_document_version"]["unique"] is True
