"""add_import_upload_session

Revision ID: 1f90f2d6a6a1
Revises: edef87f62bca
Create Date: 2026-03-07 18:30:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "1f90f2d6a6a1"
down_revision = "edef87f62bca"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_upload_session",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("resource_type", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("content_type", sqlmodel.sql.sqltypes.AutoString(length=127), nullable=False),
        sa.Column("object_key", sqlmodel.sql.sqltypes.AutoString(length=1024), nullable=False),
        sa.Column("bucket", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("strategy", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("multipart_upload_id", sqlmodel.sql.sqltypes.AutoString(length=256), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("error", sqlmodel.sql.sqltypes.AutoString(length=2000), nullable=True),
        sa.Column("uploaded_size", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta_info", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_import_upload_session_expires_at"), "import_upload_session", ["expires_at"], unique=False)
    op.create_index(op.f("ix_import_upload_session_mode"), "import_upload_session", ["mode"], unique=False)
    op.create_index(op.f("ix_import_upload_session_resource_id"), "import_upload_session", ["resource_id"], unique=False)
    op.create_index(op.f("ix_import_upload_session_resource_type"), "import_upload_session", ["resource_type"], unique=False)
    op.create_index(op.f("ix_import_upload_session_status"), "import_upload_session", ["status"], unique=False)
    op.create_index(op.f("ix_import_upload_session_user_id"), "import_upload_session", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_import_upload_session_user_id"), table_name="import_upload_session")
    op.drop_index(op.f("ix_import_upload_session_status"), table_name="import_upload_session")
    op.drop_index(op.f("ix_import_upload_session_resource_type"), table_name="import_upload_session")
    op.drop_index(op.f("ix_import_upload_session_resource_id"), table_name="import_upload_session")
    op.drop_index(op.f("ix_import_upload_session_mode"), table_name="import_upload_session")
    op.drop_index(op.f("ix_import_upload_session_expires_at"), table_name="import_upload_session")
    op.drop_table("import_upload_session")
