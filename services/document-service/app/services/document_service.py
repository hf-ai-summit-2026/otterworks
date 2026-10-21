"""DocumentService facade over the per-concern document services."""

import math
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Comment, Document, DocumentVersion, Template
from app.schemas.document import (
    CommentCreate,
    DocumentCreate,
    DocumentFromTemplate,
    DocumentPatch,
    DocumentUpdate,
    TemplateCreate,
)
from app.services.document_comments import DocumentComments
from app.services.document_crud import DocumentCrud
from app.services.document_export import DocumentExporter
from app.services.document_search import DocumentSearch
from app.services.document_templates import DocumentTemplates
from app.services.document_versions import DocumentVersions


class DocumentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.crud = DocumentCrud(db)
        self.versions = DocumentVersions(db, self.crud)
        self.searcher = DocumentSearch(db)
        self.exporter = DocumentExporter()
        self.comments = DocumentComments(db, self.crud)
        self.templates = DocumentTemplates(db, self.crud)

    # ---- Document CRUD ----

    async def create(self, data: DocumentCreate) -> Document:
        return await self.crud.create(data)

    async def get(self, document_id: UUID) -> Document | None:
        return await self.crud.get(document_id)

    async def list_documents(
        self,
        owner_id: UUID | None = None,
        folder_id: UUID | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[Document], int]:
        return await self.crud.list_documents(
            owner_id=owner_id, folder_id=folder_id, page=page, size=size
        )

    async def update(
        self, document_id: UUID, data: DocumentUpdate, updated_by: UUID | None = None
    ) -> Document | None:
        return await self.crud.update(document_id, data, updated_by=updated_by)

    async def patch(self, document_id: UUID, data: DocumentPatch) -> Document | None:
        return await self.crud.patch(document_id, data)

    async def delete(self, document_id: UUID) -> bool:
        return await self.crud.delete(document_id)

    # ---- Versions ----

    async def list_versions(self, document_id: UUID) -> list[DocumentVersion]:
        return await self.versions.list_versions(document_id)

    async def restore_version(
        self, document_id: UUID, version_id: UUID
    ) -> Document | None:
        return await self.versions.restore_version(document_id, version_id)

    # ---- Search ----

    async def search(
        self, query: str, page: int = 1, size: int = 20
    ) -> tuple[list[Document], int]:
        return await self.searcher.search(query, page=page, size=size)

    # ---- Export ----

    def export_document(self, document: Document, fmt: str) -> tuple[str, str]:
        return self.exporter.export_document(document, fmt)

    # ---- Comments ----

    async def add_comment(
        self, document_id: UUID, data: CommentCreate
    ) -> Comment | None:
        return await self.comments.add_comment(document_id, data)

    async def list_comments(self, document_id: UUID) -> list[Comment]:
        return await self.comments.list_comments(document_id)

    async def delete_comment(self, document_id: UUID, comment_id: UUID) -> bool:
        return await self.comments.delete_comment(document_id, comment_id)

    # ---- Templates ----

    async def create_template(self, data: TemplateCreate) -> Template:
        return await self.templates.create_template(data)

    async def list_templates(self) -> list[Template]:
        return await self.templates.list_templates()

    async def get_template(self, template_id: UUID) -> Template | None:
        return await self.templates.get_template(template_id)

    async def create_from_template(
        self, template_id: UUID, data: DocumentFromTemplate
    ) -> Document | None:
        return await self.templates.create_from_template(template_id, data)

    # ---- Helpers ----

    @staticmethod
    def paginate(total: int, page: int, size: int) -> int:
        return max(1, math.ceil(total / size)) if size > 0 else 1
