"""Index the owner document listing and per-document version lookups.

Revision ID: 004
Revises: 003
Create Date: 2026-10-21 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_documents_owner_id_updated_at",
        "documents",
        ["owner_id", "updated_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_document_versions_document_id_version_number",
        "document_versions",
        ["document_id", "version_number"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_versions_document_id_version_number",
        table_name="document_versions",
        if_exists=True,
    )
    op.drop_index(
        "ix_documents_owner_id_updated_at", table_name="documents", if_exists=True
    )
