"""Shared test fixtures.

Tests run against a real MongoDB (``DOC_SVC_TEST_MONGODB_URL``, default
``mongodb://localhost:27017``); every test starts from emptied collections.
"""

import os
import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.asynchronous.mongo_client import AsyncMongoClient

from app.api import documents as documents_api
from app.db.mongo import ensure_indexes, get_db
from app.main import app
from app.middleware import request_log

TEST_MONGODB_URL = os.environ.get("DOC_SVC_TEST_MONGODB_URL", "mongodb://localhost:27017")
TEST_DATABASE = "otterworks_documents_test"


@pytest.fixture(autouse=True)
def chaos_flags_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must never observe a developer's local Redis: every chaos flag reads as off."""
    monkeypatch.setattr(documents_api, "flag_active", lambda key: False)
    monkeypatch.setattr(request_log, "flag_active", lambda key: False)


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncDatabase, None]:
    client: AsyncMongoClient = AsyncMongoClient(
        TEST_MONGODB_URL, tz_aware=True, serverSelectionTimeoutMS=5000
    )
    db = client[TEST_DATABASE]
    await _clear(db)
    await ensure_indexes(db)
    try:
        yield db
    finally:
        await _clear(db)
        await client.close()


async def _clear(db: AsyncDatabase) -> None:
    """Empty every collection; keeps the collections (and their indexes) in place."""
    for name in await db.list_collection_names():
        await db[name].delete_many({})


@pytest.fixture
async def client(db_session: AsyncDatabase) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def owner_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def folder_id() -> uuid.UUID:
    return uuid.uuid4()
