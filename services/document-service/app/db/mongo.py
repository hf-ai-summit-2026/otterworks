"""MongoDB client (PyMongo async API), database handle and index management."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import structlog
from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.asynchronous.mongo_client import AsyncMongoClient

from app import telemetry
from app.config import settings
from app.models.document import (
    COMMENTS,
    DOCUMENT_VERSIONS,
    DOCUMENTS,
    STATS_ROLLUPS,
    TEMPLATES,
)

logger = structlog.get_logger()

telemetry.instrument_db()

client: AsyncMongoClient = AsyncMongoClient(
    settings.mongodb_url,
    maxPoolSize=settings.db_pool_size + settings.db_max_overflow,
    serverSelectionTimeoutMS=settings.mongodb_server_selection_timeout_ms,
    tz_aware=True,
    appname=settings.app_name,
)
database: AsyncDatabase = client[settings.mongodb_database]

# Indexes replace the Alembic migrations: they are idempotent and applied on boot.
INDEXES: dict[str, list[IndexModel]] = {
    DOCUMENTS: [
        IndexModel(
            [
                ("owner_id", ASCENDING),
                ("is_deleted", ASCENDING),
                ("is_template", ASCENDING),
                ("updated_at", DESCENDING),
            ],
            name="documents_owner_live_updated",
        ),
        IndexModel(
            [("folder_id", ASCENDING), ("updated_at", DESCENDING)],
            name="documents_folder_updated",
        ),
        IndexModel([("updated_at", DESCENDING)], name="documents_updated"),
    ],
    DOCUMENT_VERSIONS: [
        IndexModel(
            [("document_id", ASCENDING), ("version_number", DESCENDING)],
            name="versions_document_version",
            unique=True,
        ),
    ],
    COMMENTS: [
        IndexModel(
            [("document_id", ASCENDING), ("created_at", ASCENDING)],
            name="comments_document_created",
        ),
    ],
    TEMPLATES: [IndexModel([("name", ASCENDING)], name="templates_name")],
    STATS_ROLLUPS: [
        IndexModel([("window_start", ASCENDING)], name="rollups_window"),
        IndexModel(
            [("window_start", ASCENDING), ("computed_by", ASCENDING)],
            name="rollups_window_host",
        ),
    ],
}


async def ensure_indexes(db: AsyncDatabase) -> dict[str, list[str]]:
    """Create every index the service relies on. Safe to run on every boot."""
    created: dict[str, list[str]] = {}
    for collection, models in INDEXES.items():
        created[collection] = await db[collection].create_indexes(models)
    logger.info("mongodb_indexes_ensured", collections=sorted(created))
    return created


async def ping(db: AsyncDatabase) -> None:
    await db.command("ping")


async def get_db() -> AsyncGenerator[AsyncDatabase, None]:
    """Dependency injection for the database handle."""
    yield database
