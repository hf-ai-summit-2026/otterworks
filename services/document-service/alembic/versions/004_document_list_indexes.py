"""Index the document list and its recent-versions lookup.

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
        "ix_documents_owner_listing",
        "documents",
        ["owner_id", "is_deleted", "is_template", "updated_at"],
    )
    op.create_index(
        "ix_document_versions_document_version",
        "document_versions",
        ["document_id", "version_number"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_versions_document_version", table_name="document_versions")
    op.drop_index("ix_documents_owner_listing", table_name="documents")
