"""Document create/read/update/delete and listing."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentVersion
from app.schemas.document import DocumentCreate, DocumentPatch, DocumentUpdate
from app.services.event_publisher import event_publisher


def _word_count(text: str) -> int:
    return len(text.split()) if text else 0


def _document_index_payload(document: Document) -> dict[str, object]:
    return {
        "id": document.id,
        "title": document.title,
        "content": document.content,
        "owner_id": document.owner_id,
        "tags": [],
        "created_at": document.created_at,
        "updated_at": document.updated_at,
    }


class DocumentCrud:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: DocumentCreate) -> Document:
        document = Document(
            title=data.title,
            content=data.content,
            content_type=data.content_type,
            owner_id=data.owner_id,
            folder_id=data.folder_id,
            word_count=_word_count(data.content),
            version=1,
        )
        self.db.add(document)
        await self.db.flush()

        version = DocumentVersion(
            document_id=document.id,
            version_number=1,
            title=data.title,
            content=data.content,
            created_by=data.owner_id,
        )
        self.db.add(version)
        await self.db.commit()
        await self.db.refresh(document)

        await event_publisher.publish(
            "document_created",
            _document_index_payload(document),
        )
        return document

    async def get(self, document_id: UUID) -> Document | None:
        result = await self.db.execute(
            select(Document).where(
                Document.id == document_id, Document.is_deleted.is_(False)
            )
        )
        return result.scalar_one_or_none()

    async def list_documents(
        self,
        owner_id: UUID | None = None,
        folder_id: UUID | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[Document], int]:
        base = select(Document).where(
            Document.is_deleted.is_(False), Document.is_template.is_(False)
        )
        if owner_id:
            base = base.where(Document.owner_id == owner_id)
        if folder_id:
            base = base.where(Document.folder_id == folder_id)

        count_q = select(func.count()).select_from(base.subquery())
        total = (await self.db.execute(count_q)).scalar_one()

        query = base.order_by(Document.updated_at.desc())
        query = query.offset((page - 1) * size).limit(size)
        result = await self.db.execute(query)
        documents = list(result.scalars().all())

        # TODO: This is slow for large result sets (ETL-445, deferred Q2 2024)
        for doc in documents:
            ver_result = await self.db.execute(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == doc.id)
                .order_by(DocumentVersion.version_number.desc())
                .limit(5)
            )
            doc.recent_versions = list(ver_result.scalars().all())

        return documents, total

    async def update(
        self, document_id: UUID, data: DocumentUpdate, updated_by: UUID | None = None
    ) -> Document | None:
        document = await self.get(document_id)
        if not document:
            return None

        document.title = data.title
        document.content = data.content
        document.content_type = data.content_type
        document.folder_id = data.folder_id
        document.word_count = _word_count(data.content)
        document.version += 1

        version = DocumentVersion(
            document_id=document.id,
            version_number=document.version,
            title=data.title,
            content=data.content,
            created_by=updated_by or document.owner_id,
        )
        self.db.add(version)
        await self.db.commit()
        await self.db.refresh(document)

        await event_publisher.publish(
            "document_updated",
            _document_index_payload(document),
        )
        return document

    async def patch(self, document_id: UUID, data: DocumentPatch) -> Document | None:
        document = await self.get(document_id)
        if not document:
            return None

        changed = False
        if "title" in data.model_fields_set:
            document.title = data.title
            changed = True
        if "content" in data.model_fields_set:
            document.content = data.content
            document.word_count = _word_count(data.content) if data.content else 0
            changed = True
        if "content_type" in data.model_fields_set:
            document.content_type = data.content_type
            changed = True
        if "folder_id" in data.model_fields_set:
            document.folder_id = data.folder_id
            changed = True

        if changed:
            document.version += 1
            version = DocumentVersion(
                document_id=document.id,
                version_number=document.version,
                title=document.title,
                content=document.content,
                created_by=document.owner_id,
            )
            self.db.add(version)

        await self.db.commit()
        await self.db.refresh(document)

        if changed:
            await event_publisher.publish(
                "document_updated",
                _document_index_payload(document),
            )
        return document

    async def delete(self, document_id: UUID) -> bool:
        document = await self.get(document_id)
        if not document:
            return False
        document.is_deleted = True
        await self.db.commit()

        await event_publisher.publish(
            "document_deleted", {"id": document_id, "type": "document"}
        )
        return True
