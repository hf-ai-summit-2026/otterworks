"""Document domain models stored as MongoDB documents.

Each model is a plain dataclass whose attribute names match the API schemas
(``from_attributes``) and whose ``to_doc``/``from_doc`` methods map it onto a
MongoDB document. UUIDs are stored as strings so they read naturally in Atlas
and Compass; timestamps are stored as BSON dates (millisecond precision).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from typing import Any, ClassVar, TypeVar

DOCUMENTS = "documents"
DOCUMENT_VERSIONS = "document_versions"
COMMENTS = "comments"
TEMPLATES = "templates"
STATS_ROLLUPS = "document_stats_rollups"


def _utcnow() -> datetime:
    """Now in UTC, truncated to the millisecond precision BSON dates keep."""
    now = datetime.now(UTC)
    return now.replace(microsecond=now.microsecond - now.microsecond % 1000)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


T = TypeVar("T", bound="MongoModel")


@dataclass
class MongoModel:
    """Base for models persisted in a MongoDB collection."""

    collection: ClassVar[str]
    _uuid_fields: ClassVar[frozenset[str]] = frozenset()
    _datetime_fields: ClassVar[frozenset[str]] = frozenset()
    _transient: ClassVar[frozenset[str]] = frozenset()

    def to_doc(self) -> dict[str, Any]:
        doc: dict[str, Any] = {}
        for f in fields(self):
            if f.name in self._transient:
                continue
            value = getattr(self, f.name)
            if f.name in self._uuid_fields and value is not None:
                value = str(value)
            key = "_id" if f.name == "id" else f.name
            doc[key] = value
        return doc

    @classmethod
    def from_doc(cls: type[T], doc: dict[str, Any]) -> T:
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            if f.name in cls._transient:
                continue
            key = "_id" if f.name == "id" else f.name
            if key not in doc:
                continue
            value = doc[key]
            if f.name in cls._uuid_fields and value is not None:
                value = uuid.UUID(str(value))
            elif f.name in cls._datetime_fields and value is not None:
                value = _as_utc(value)
            kwargs[f.name] = value
        return cls(**kwargs)


@dataclass
class Document(MongoModel):
    collection: ClassVar[str] = DOCUMENTS
    _uuid_fields: ClassVar[frozenset[str]] = frozenset({"id", "owner_id", "folder_id"})
    _datetime_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at"})
    _transient: ClassVar[frozenset[str]] = frozenset({"recent_versions"})

    title: str
    owner_id: uuid.UUID
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    content: str = ""
    content_type: str = "text/markdown"
    folder_id: uuid.UUID | None = None
    is_deleted: bool = False
    is_template: bool = False
    word_count: int = 0
    version: int = 1
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    recent_versions: list[DocumentVersion] = field(default_factory=list)


@dataclass
class DocumentVersion(MongoModel):
    collection: ClassVar[str] = DOCUMENT_VERSIONS
    _uuid_fields: ClassVar[frozenset[str]] = frozenset({"id", "document_id", "created_by"})
    _datetime_fields: ClassVar[frozenset[str]] = frozenset({"created_at"})

    document_id: uuid.UUID
    version_number: int
    title: str
    content: str
    created_by: uuid.UUID
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class Comment(MongoModel):
    collection: ClassVar[str] = COMMENTS
    _uuid_fields: ClassVar[frozenset[str]] = frozenset({"id", "document_id", "author_id"})
    _datetime_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at"})

    document_id: uuid.UUID
    author_id: uuid.UUID
    content: str
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)


@dataclass
class DocumentStatsRollup(MongoModel):
    """Hourly usage totals computed by the scheduled rollup job."""

    collection: ClassVar[str] = STATS_ROLLUPS
    _uuid_fields: ClassVar[frozenset[str]] = frozenset({"id"})
    _datetime_fields: ClassVar[frozenset[str]] = frozenset({"window_start", "created_at"})

    window_start: datetime
    documents_total: int
    versions_total: int
    words_total: int
    computed_by: str
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class Template(MongoModel):
    collection: ClassVar[str] = TEMPLATES
    _uuid_fields: ClassVar[frozenset[str]] = frozenset({"id", "created_by"})
    _datetime_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at"})

    name: str
    created_by: uuid.UUID
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    description: str = ""
    content: str = ""
    content_type: str = "text/markdown"
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
