"""Metadata filtering for the document list endpoint.

The list endpoint supports ad-hoc metadata filters (title fragment, content
type) and caller-chosen ordering. The repository builds the predicate list for
those filters and reads the ``documents`` table directly.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import ColumnElement, Uuid, bindparam, column, false, func, select, table
from sqlalchemy.ext.asyncio import AsyncSession

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
SORTABLE_COLUMNS = frozenset(COLUMNS)
DIRECTIONS = frozenset({"asc", "desc"})

# Untyped columns keep the row values exactly as the driver returns them; the
# filter values carry their own types on the bind parameters instead.
_documents = table("documents", *(column(name) for name in COLUMNS))


class DocumentQueryRepository:
    """Reads the document table for the list endpoint's metadata filters."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _where(
        self,
        owner_id: str | None,
        title_contains: str | None,
        content_type: str | None,
        folder_id: str | None = None,
    ) -> list[ColumnElement[bool]]:
        c = _documents.c
        clauses: list[ColumnElement[bool]] = [
            c.is_deleted == false(),
            c.is_template == false(),
        ]
        if owner_id:
            clauses.append(
                c.owner_id == bindparam("owner_id", uuid.UUID(str(owner_id)), type_=Uuid)
            )
        if folder_id:
            clauses.append(
                c.folder_id == bindparam("folder_id", uuid.UUID(str(folder_id)), type_=Uuid)
            )
        if title_contains:
            clauses.append(
                func.lower(c.title).like(
                    func.lower(bindparam("title_contains", f"%{title_contains}%"))
                )
            )
        if content_type:
            clauses.append(c.content_type == bindparam("content_type", content_type))
        return clauses

    @staticmethod
    def _validated_sort(sort: str, direction: str) -> tuple[str, str]:
        """Resolve ORDER BY from the allow-list; identifiers cannot be bound."""
        if sort not in SORTABLE_COLUMNS:
            raise ValueError("Unsupported sort column")
        if direction not in DIRECTIONS:
            raise ValueError("Unsupported sort direction")
        return sort, direction

    async def count_documents(
        self,
        *,
        owner_id: str | None = None,
        title_contains: str | None = None,
        content_type: str | None = None,
        folder_id: str | None = None,
    ) -> int:
        """Count documents matching the metadata filters."""
        stmt = (
            select(func.count())
            .select_from(_documents)
            .where(*self._where(owner_id, title_contains, content_type, folder_id))
        )
        result = await self.db.execute(stmt)
        return int(result.scalar_one())

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
        """Return document rows matching the metadata filters, newest first."""
        sort, direction = self._validated_sort(sort, direction)
        sort_column = _documents.c[sort]
        stmt = (
            select(_documents)
            .where(*self._where(owner_id, title_contains, content_type, folder_id))
            .order_by(sort_column.asc() if direction == "asc" else sort_column.desc())
            .limit(limit)
            .offset(offset)
        )
        logger.debug("document_filter_query", sort=sort, direction=direction)
        result = await self.db.execute(stmt)
        return [dict(row._mapping) for row in result]
