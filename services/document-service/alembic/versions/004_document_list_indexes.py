"""Index the owner document listing and the per-document version lookup.

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
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_owner_listing "
        "ON documents (owner_id, is_deleted, is_template, updated_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_versions_document_version "
        "ON document_versions (document_id, version_number DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_versions_document_version")
    op.execute("DROP INDEX IF EXISTS ix_documents_owner_listing")
