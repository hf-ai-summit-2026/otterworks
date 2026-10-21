"""One-off copy of document-service data from PostgreSQL to MongoDB.

Reads the five document-service tables through asyncpg and upserts each row
into the matching MongoDB collection (keyed on the original UUID), so the
script is idempotent and can be re-run to catch up after a dual-write window.

Usage::

    poetry install --with migration
    poetry run python scripts/migrate_postgres_to_mongodb.py \\
        --postgres-url postgresql://user:pass@host:5432/otterworks \\
        --mongodb-url "$DOC_SVC_MONGODB_URL" --database otterworks_documents

Add ``--dry-run`` to count rows without writing.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
from pymongo import UpdateOne
from pymongo.asynchronous.mongo_client import AsyncMongoClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.mongo import INDEXES  # noqa: E402
from app.models.document import (  # noqa: E402
    COMMENTS,
    DOCUMENT_VERSIONS,
    DOCUMENTS,
    STATS_ROLLUPS,
    TEMPLATES,
)

# table -> (collection, uuid columns)
TABLES: dict[str, tuple[str, tuple[str, ...]]] = {
    "documents": (DOCUMENTS, ("id", "owner_id", "folder_id")),
    "document_versions": (DOCUMENT_VERSIONS, ("id", "document_id", "created_by")),
    "comments": (COMMENTS, ("id", "document_id", "author_id")),
    "templates": (TEMPLATES, ("id", "created_by")),
    "document_stats_rollups": (STATS_ROLLUPS, ("id",)),
}
BATCH = 1000


def _convert(row: asyncpg.Record, uuid_columns: tuple[str, ...]) -> dict[str, Any]:
    doc: dict[str, Any] = {}
    for key, value in dict(row).items():
        if key in uuid_columns and isinstance(value, uuid.UUID):
            value = str(value)
        elif isinstance(value, datetime):
            value = value if value.tzinfo else value.replace(tzinfo=UTC)
        doc["_id" if key == "id" else key] = value
    return doc


async def migrate_table(
    pg: asyncpg.Connection, mongo_db: Any, table: str, dry_run: bool
) -> tuple[int, int]:
    collection_name, uuid_columns = TABLES[table]
    collection = mongo_db[collection_name]
    total = await pg.fetchval(f"SELECT count(*) FROM {table}")  # noqa: S608 - table from TABLES
    if dry_run:
        return total, 0

    written = 0
    async with pg.transaction():
        batch: list[UpdateOne] = []
        async for row in pg.cursor(f"SELECT * FROM {table} ORDER BY id"):  # noqa: S608
            doc = _convert(row, uuid_columns)
            batch.append(UpdateOne({"_id": doc["_id"]}, {"$set": doc}, upsert=True))
            if len(batch) >= BATCH:
                result = await collection.bulk_write(batch, ordered=False)
                written += result.upserted_count + result.modified_count + result.matched_count
                batch = []
        if batch:
            result = await collection.bulk_write(batch, ordered=False)
            written += result.upserted_count + result.modified_count + result.matched_count
    return total, written


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--postgres-url", required=True)
    parser.add_argument("--mongodb-url", required=True)
    parser.add_argument("--database", default="otterworks_documents")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    pg = await asyncpg.connect(args.postgres_url)
    mongo = AsyncMongoClient(args.mongodb_url, tz_aware=True)
    mongo_db = mongo[args.database]
    try:
        if not args.dry_run:
            for collection, models in INDEXES.items():
                await mongo_db[collection].create_indexes(models)
        for table in TABLES:
            total, written = await migrate_table(pg, mongo_db, table, args.dry_run)
            print(f"{table:>24}: {total} rows in postgres, {written} written to mongodb")
    finally:
        await pg.close()
        await mongo.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
