"""Index the owner document listing and recent-versions lookups.

Revision ID: 004
Revises: 003
Create Date: 2026-10-21 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_document_versions_document_id_version_number",
        "document_versions",
        ["document_id", "version_number"],
    )
    op.create_index(
        "ix_documents_owner_id_updated_at",
        "documents",
        ["owner_id", sa.text("updated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_documents_owner_id_updated_at", table_name="documents")
    op.drop_index(
        "ix_document_versions_document_id_version_number",
        table_name="document_versions",
    )
