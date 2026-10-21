"""Template API endpoints."""

import structlog
from fastapi import APIRouter, Depends, status
from pymongo.asynchronous.database import AsyncDatabase

from app.db.mongo import get_db
from app.schemas.document import TemplateCreate, TemplateResponse
from app.services.document_service import DocumentService

logger = structlog.get_logger()
router = APIRouter()


@router.get("/", response_model=list[TemplateResponse])
async def list_templates(
    db: AsyncDatabase = Depends(get_db),
):
    """List all templates."""
    service = DocumentService(db)
    return await service.list_templates()


@router.post(
    "/", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED
)
async def create_template(
    body: TemplateCreate,
    db: AsyncDatabase = Depends(get_db),
):
    """Create a new template."""
    service = DocumentService(db)
    template = await service.create_template(body)
    logger.info("template_created", template_id=str(template.id))
    return template
