"""Metadata filtering for the document list endpoint.

The list endpoint supports ad-hoc metadata filters (title fragment, content
type) and caller-chosen ordering. The repository builds the predicate list for
those filters and reads the ``documents`` table directly.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import column, false, func, select, table
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


DOCUMENTS = table("documents", *(column(name) for name in COLUMNS))
SORT_DIRECTIONS = frozenset(("asc", "desc"))


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
    ) -> list[Any]:
        c = DOCUMENTS.c
        clauses: list[Any] = [c.is_deleted == false(), c.is_template == false()]
        if owner_id:
            clauses.append(c.owner_id == owner_id)
        if folder_id:
            clauses.append(c.folder_id == folder_id)
        if title_contains:
            clauses.append(func.lower(c.title).like(func.lower(f"%{title_contains}%")))
        if content_type:
            clauses.append(c.content_type == content_type)
        return clauses

    @staticmethod
    def _order_by(sort: str, direction: str) -> Any:
        name = sort.lower()
        order = direction.lower()
        if name not in DOCUMENTS.c:
            raise ValueError(f"unsupported sort column {sort!r}")
        if order not in SORT_DIRECTIONS:
            raise ValueError(f"unsupported sort direction {direction!r}")
        col = DOCUMENTS.c[name]
        return col.asc() if order == "asc" else col.desc()

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
            .select_from(DOCUMENTS)
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
        stmt = (
            select(DOCUMENTS)
            .where(*self._where(owner_id, title_contains, content_type, folder_id))
            .order_by(self._order_by(sort, direction))
            .limit(int(limit))
            .offset(int(offset))
        )
        logger.debug("document_filter_query", sort=sort, direction=direction)
        result = await self.db.execute(stmt)
        return [dict(row._mapping) for row in result]
