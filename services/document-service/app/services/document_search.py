"""Title/content substring search over live documents."""

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document


def _like_pattern(query: str) -> str:
    """Contains-pattern for ILIKE with the LIKE wildcards in `query` matched literally."""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class DocumentSearch:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def search(
        self, query: str, page: int = 1, size: int = 20
    ) -> tuple[list[Document], int]:
        pattern = _like_pattern(query)
        base = select(Document).where(
            Document.is_deleted.is_(False),
            Document.is_template.is_(False),
            or_(
                Document.title.ilike(pattern),
                Document.content.ilike(pattern),
            ),
        )
        count_q = select(func.count()).select_from(base.subquery())
        total = (await self.db.execute(count_q)).scalar_one()

        q = base.order_by(Document.updated_at.desc())
        q = q.offset((page - 1) * size).limit(size)
        result = await self.db.execute(q)
        return list(result.scalars().all()), total
