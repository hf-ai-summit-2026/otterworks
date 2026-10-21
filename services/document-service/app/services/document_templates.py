"""Document templates and creating documents from them."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, Template
from app.schemas.document import DocumentCreate, DocumentFromTemplate, TemplateCreate
from app.services.document_crud import DocumentCrud


class DocumentTemplates:
    def __init__(self, db: AsyncSession, crud: DocumentCrud):
        self.db = db
        self.crud = crud

    async def create_template(self, data: TemplateCreate) -> Template:
        template = Template(
            name=data.name,
            description=data.description,
            content=data.content,
            content_type=data.content_type,
            created_by=data.created_by,
        )
        self.db.add(template)
        await self.db.commit()
        await self.db.refresh(template)
        return template

    async def list_templates(self) -> list[Template]:
        result = await self.db.execute(
            select(Template).order_by(Template.name.asc())
        )
        return list(result.scalars().all())

    async def get_template(self, template_id: UUID) -> Template | None:
        result = await self.db.execute(
            select(Template).where(Template.id == template_id)
        )
        return result.scalar_one_or_none()

    async def create_from_template(
        self, template_id: UUID, data: DocumentFromTemplate
    ) -> Document | None:
        template = await self.get_template(template_id)
        if not template:
            return None

        create_data = DocumentCreate(
            title=data.title,
            content=template.content,
            content_type=template.content_type,
            owner_id=data.owner_id,
            folder_id=data.folder_id,
        )
        return await self.crud.create(create_data)
