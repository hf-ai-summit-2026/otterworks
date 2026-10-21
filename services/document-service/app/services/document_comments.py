"""Comments on documents."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Comment
from app.schemas.document import CommentCreate
from app.services.document_crud import DocumentCrud
from app.services.event_publisher import event_publisher


class DocumentComments:
    def __init__(self, db: AsyncSession, crud: DocumentCrud):
        self.db = db
        self.crud = crud

    async def add_comment(
        self, document_id: UUID, data: CommentCreate
    ) -> Comment | None:
        document = await self.crud.get(document_id)
        if not document:
            return None

        comment = Comment(
            document_id=document_id,
            author_id=data.author_id,
            content=data.content,
        )
        self.db.add(comment)
        await self.db.commit()
        await self.db.refresh(comment)

        await event_publisher.publish(
            "comment_added",
            {
                "comment_id": comment.id,
                "document_id": document_id,
                "author_id": data.author_id,
            },
        )
        return comment

    async def list_comments(self, document_id: UUID) -> list[Comment]:
        result = await self.db.execute(
            select(Comment)
            .where(Comment.document_id == document_id)
            .order_by(Comment.created_at.asc())
        )
        return list(result.scalars().all())

    async def delete_comment(self, document_id: UUID, comment_id: UUID) -> bool:
        result = await self.db.execute(
            select(Comment).where(
                Comment.id == comment_id, Comment.document_id == document_id
            )
        )
        comment = result.scalar_one_or_none()
        if not comment:
            return False
        await self.db.delete(comment)
        await self.db.commit()
        return True
