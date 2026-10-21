"""Document business logic service backed by MongoDB."""

import html as html_mod
import math
import re
from collections import defaultdict
from typing import Any
from uuid import UUID

import structlog
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from app.models.document import (
    COMMENTS,
    DOCUMENT_VERSIONS,
    DOCUMENTS,
    TEMPLATES,
    Comment,
    Document,
    DocumentVersion,
    Template,
    _utcnow,
)
from app.schemas.document import (
    CommentCreate,
    DocumentCreate,
    DocumentFromTemplate,
    DocumentPatch,
    DocumentUpdate,
    TemplateCreate,
)
from app.services.event_publisher import event_publisher

logger = structlog.get_logger()

RECENT_VERSIONS = 5
LIVE_DOCUMENT = {"is_deleted": False, "is_template": False}


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


class DocumentService:
    def __init__(self, db: AsyncDatabase):
        self.db = db
        self.documents = db[DOCUMENTS]
        self.versions = db[DOCUMENT_VERSIONS]
        self.comments = db[COMMENTS]
        self.templates = db[TEMPLATES]

    # ---- Document CRUD ----

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
        await self.documents.insert_one(document.to_doc())
        await self._add_version(document, created_by=data.owner_id)

        await event_publisher.publish(
            "document_created",
            _document_index_payload(document),
        )
        return document

    async def get(self, document_id: UUID) -> Document | None:
        doc = await self.documents.find_one({"_id": str(document_id), "is_deleted": False})
        return Document.from_doc(doc) if doc else None

    async def list_documents(
        self,
        owner_id: UUID | None = None,
        folder_id: UUID | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[Document], int]:
        query: dict[str, Any] = dict(LIVE_DOCUMENT)
        if owner_id:
            query["owner_id"] = str(owner_id)
        if folder_id:
            query["folder_id"] = str(folder_id)

        total = await self.documents.count_documents(query)
        cursor = (
            self.documents.find(query)
            .sort("updated_at", DESCENDING)
            .skip((page - 1) * size)
            .limit(size)
        )
        documents = [Document.from_doc(doc) async for doc in cursor]

        # One query for the recent versions of the whole page (no per-document fan-out).
        recent: dict[str, list[DocumentVersion]] = defaultdict(list)
        if documents:
            ver_cursor = self.versions.find(
                {"document_id": {"$in": [str(d.id) for d in documents]}}
            ).sort([("document_id", ASCENDING), ("version_number", DESCENDING)])
            async for ver in ver_cursor:
                bucket = recent[ver["document_id"]]
                if len(bucket) < RECENT_VERSIONS:
                    bucket.append(DocumentVersion.from_doc(ver))
        for doc in documents:
            doc.recent_versions = recent.get(str(doc.id), [])

        return documents, total

    async def update(
        self, document_id: UUID, data: DocumentUpdate, updated_by: UUID | None = None
    ) -> Document | None:
        document = await self.get(document_id)
        if not document:
            return None

        changes = {
            "title": data.title,
            "content": data.content,
            "content_type": data.content_type,
            "folder_id": str(data.folder_id) if data.folder_id else None,
            "word_count": _word_count(data.content),
        }
        document = await self._apply_revision(document, changes)
        await self._add_version(document, created_by=updated_by or document.owner_id)

        await event_publisher.publish(
            "document_updated",
            _document_index_payload(document),
        )
        return document

    async def patch(self, document_id: UUID, data: DocumentPatch) -> Document | None:
        document = await self.get(document_id)
        if not document:
            return None

        changes: dict[str, Any] = {}
        if "title" in data.model_fields_set:
            changes["title"] = data.title
        if "content" in data.model_fields_set:
            changes["content"] = data.content
            changes["word_count"] = _word_count(data.content) if data.content else 0
        if "content_type" in data.model_fields_set:
            changes["content_type"] = data.content_type
        if "folder_id" in data.model_fields_set:
            changes["folder_id"] = str(data.folder_id) if data.folder_id else None

        if not changes:
            return document

        document = await self._apply_revision(document, changes)
        await self._add_version(document, created_by=document.owner_id)
        await event_publisher.publish(
            "document_updated",
            _document_index_payload(document),
        )
        return document

    async def delete(self, document_id: UUID) -> bool:
        result = await self.documents.update_one(
            {"_id": str(document_id), "is_deleted": False},
            {"$set": {"is_deleted": True, "updated_at": _utcnow()}},
        )
        if result.matched_count == 0:
            return False

        await event_publisher.publish(
            "document_deleted", {"id": document_id, "type": "document"}
        )
        return True

    # ---- Versions ----

    async def list_versions(self, document_id: UUID) -> list[DocumentVersion]:
        cursor = self.versions.find({"document_id": str(document_id)}).sort(
            "version_number", ASCENDING
        )
        return [DocumentVersion.from_doc(v) async for v in cursor]

    async def restore_version(
        self, document_id: UUID, version_id: UUID
    ) -> Document | None:
        document = await self.get(document_id)
        if not document:
            return None

        raw = await self.versions.find_one(
            {"_id": str(version_id), "document_id": str(document_id)}
        )
        if not raw:
            return None
        ver = DocumentVersion.from_doc(raw)

        changes = {
            "title": ver.title,
            "content": ver.content,
            "word_count": _word_count(ver.content),
        }
        document = await self._apply_revision(document, changes)
        await self._add_version(document, created_by=document.owner_id)

        await event_publisher.publish(
            "document_updated",
            {
                **_document_index_payload(document),
                "restored_from": version_id,
            },
        )
        return document

    # ---- Search ----

    async def search(
        self, query: str, page: int = 1, size: int = 20
    ) -> tuple[list[Document], int]:
        pattern = {"$regex": re.escape(query), "$options": "i"}
        mongo_query: dict[str, Any] = {
            **LIVE_DOCUMENT,
            "$or": [{"title": pattern}, {"content": pattern}],
        }
        total = await self.documents.count_documents(mongo_query)
        cursor = (
            self.documents.find(mongo_query)
            .sort("updated_at", DESCENDING)
            .skip((page - 1) * size)
            .limit(size)
        )
        return [Document.from_doc(d) async for d in cursor], total

    # ---- Export ----

    def export_document(self, document: Document, fmt: str) -> tuple[str, str]:
        if fmt == "html":
            safe_title = html_mod.escape(document.title)
            safe_content = html_mod.escape(document.content)
            markup = (
                f"<html><head><title>{safe_title}</title></head>"
                f"<body><h1>{safe_title}</h1>"
                f"<div>{safe_content}</div></body></html>"
            )
            return markup, "text/html"
        if fmt == "markdown":
            md = f"# {document.title}\n\n{document.content}"
            return md, "text/markdown"
        # pdf → return simple text representation
        text = f"TITLE: {document.title}\n\n{document.content}"
        return text, "application/pdf"

    # ---- Comments ----

    async def add_comment(
        self, document_id: UUID, data: CommentCreate
    ) -> Comment | None:
        document = await self.get(document_id)
        if not document:
            return None

        comment = Comment(
            document_id=document_id,
            author_id=data.author_id,
            content=data.content,
        )
        await self.comments.insert_one(comment.to_doc())

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
        cursor = self.comments.find({"document_id": str(document_id)}).sort(
            "created_at", ASCENDING
        )
        return [Comment.from_doc(c) async for c in cursor]

    async def delete_comment(self, document_id: UUID, comment_id: UUID) -> bool:
        result = await self.comments.delete_one(
            {"_id": str(comment_id), "document_id": str(document_id)}
        )
        return result.deleted_count == 1

    # ---- Templates ----

    async def create_template(self, data: TemplateCreate) -> Template:
        template = Template(
            name=data.name,
            description=data.description,
            content=data.content,
            content_type=data.content_type,
            created_by=data.created_by,
        )
        await self.templates.insert_one(template.to_doc())
        return template

    async def list_templates(self) -> list[Template]:
        cursor = self.templates.find({}).sort("name", ASCENDING)
        return [Template.from_doc(t) async for t in cursor]

    async def get_template(self, template_id: UUID) -> Template | None:
        doc = await self.templates.find_one({"_id": str(template_id)})
        return Template.from_doc(doc) if doc else None

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
        return await self.create(create_data)

    # ---- Helpers ----

    async def _apply_revision(self, document: Document, changes: dict[str, Any]) -> Document:
        """Apply `changes`, bump the version and refresh updated_at atomically."""
        updated = await self.documents.find_one_and_update(
            {"_id": str(document.id), "is_deleted": False},
            {"$set": {**changes, "updated_at": _utcnow()}, "$inc": {"version": 1}},
            return_document=ReturnDocument.AFTER,
        )
        return Document.from_doc(updated)

    async def _add_version(self, document: Document, created_by: UUID) -> DocumentVersion:
        version = DocumentVersion(
            document_id=document.id,
            version_number=document.version,
            title=document.title,
            content=document.content,
            created_by=created_by,
        )
        await self.versions.insert_one(version.to_doc())
        return version

    @staticmethod
    def paginate(total: int, page: int, size: int) -> int:
        return max(1, math.ceil(total / size)) if size > 0 else 1
