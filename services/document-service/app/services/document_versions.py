"""Document version history and restore."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentVersion
from app.services.document_crud import (
    DocumentCrud,
    _document_index_payload,
    _word_count,
)
from app.services.event_publisher import event_publisher


class DocumentVersions:
    def __init__(self, db: AsyncSession, crud: DocumentCrud):
        self.db = db
        self.crud = crud

    async def list_versions(self, document_id: UUID) -> list[DocumentVersion]:
        result = await self.db.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number.asc())
        )
        return list(result.scalars().all())

    async def restore_version(
        self, document_id: UUID, version_id: UUID
    ) -> Document | None:
        document = await self.crud.get(document_id)
        if not document:
            return None

        result = await self.db.execute(
            select(DocumentVersion).where(
                DocumentVersion.id == version_id,
                DocumentVersion.document_id == document_id,
            )
        )
        ver = result.scalar_one_or_none()
        if not ver:
            return None

        document.title = ver.title
        document.content = ver.content
        document.word_count = _word_count(ver.content)
        document.version += 1

        new_ver = DocumentVersion(
            document_id=document.id,
            version_number=document.version,
            title=ver.title,
            content=ver.content,
            created_by=document.owner_id,
        )
        self.db.add(new_ver)
        await self.db.commit()
        await self.db.refresh(document)

        await event_publisher.publish(
            "document_updated",
            {
                **_document_index_payload(document),
                "restored_from": version_id,
            },
        )
        return document
