"""Metadata filtering for the document list endpoint.

The list endpoint supports ad-hoc metadata filters (title fragment, content
type) and caller-chosen ordering. The repository builds the MongoDB filter for
those and reads the ``documents`` collection directly.
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from pymongo import ASCENDING, DESCENDING
from pymongo.asynchronous.database import AsyncDatabase

from app.models.document import DOCUMENTS

logger = structlog.get_logger()

COLUMNS = (
    "id",
    "title",
    "content",
    "content_type",
    "owner_id",
    "folder_id",
    "is_deleted",
    "is_template",
    "word_count",
    "version",
    "created_at",
    "updated_at",
)
DIRECTIONS = {"asc": ASCENDING, "desc": DESCENDING}


class DocumentQueryRepository:
    """Reads the documents collection for the list endpoint's metadata filters."""

    def __init__(self, db: AsyncDatabase):
        self.db = db
        self.documents = db[DOCUMENTS]

    def _filter(
        self,
        owner_id: str | None,
        title_contains: str | None,
        content_type: str | None,
        folder_id: str | None = None,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {"is_deleted": False, "is_template": False}
        if owner_id:
            query["owner_id"] = owner_id
        if folder_id:
            query["folder_id"] = folder_id
        if title_contains:
            query["title"] = {"$regex": re.escape(title_contains), "$options": "i"}
        if content_type:
            query["content_type"] = content_type
        return query

    async def count_documents(
        self,
        *,
        owner_id: str | None = None,
        title_contains: str | None = None,
        content_type: str | None = None,
        folder_id: str | None = None,
    ) -> int:
        """Count documents matching the metadata filters."""
        return await self.documents.count_documents(
            self._filter(owner_id, title_contains, content_type, folder_id)
        )

    async def search_documents(
        self,
        *,
        owner_id: str | None = None,
        title_contains: str | None = None,
        content_type: str | None = None,
        folder_id: str | None = None,
        sort: str = "updated_at",
        direction: str = "desc",
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return document rows matching the metadata filters in the requested order.

        Raises ``ValueError`` for a sort column or direction the API does not expose.
        """
        if sort not in COLUMNS:
            raise ValueError(f"unknown sort column: {sort!r}")
        if direction not in DIRECTIONS:
            raise ValueError(f"unknown sort direction: {direction!r}")
        logger.debug("document_filter_query", sort=sort, direction=direction)
        sort_key = "_id" if sort == "id" else sort
        cursor = (
            self.documents.find(self._filter(owner_id, title_contains, content_type, folder_id))
            .sort(sort_key, DIRECTIONS[direction])
            .skip(offset)
            .limit(limit)
        )
        rows: list[dict[str, Any]] = []
        async for doc in cursor:
            row = {column: doc.get(column) for column in COLUMNS if column != "id"}
            row["id"] = doc["_id"]
            rows.append(row)
        return rows
