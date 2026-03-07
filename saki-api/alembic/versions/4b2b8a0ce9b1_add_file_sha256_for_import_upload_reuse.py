"""add_file_sha256_for_import_upload_reuse

Revision ID: 4b2b8a0ce9b1
Revises: 1f90f2d6a6a1
Create Date: 2026-03-08 11:20:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4b2b8a0ce9b1"
down_revision = "1f90f2d6a6a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "import_upload_session",
        sa.Column("file_sha256", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_import_upload_session_user_hash_size_status_expires",
        "import_upload_session",
        ["user_id", "file_sha256", "size", "status", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_import_upload_session_user_hash_size_status_expires", table_name="import_upload_session")
    op.drop_column("import_upload_session", "file_sha256")
