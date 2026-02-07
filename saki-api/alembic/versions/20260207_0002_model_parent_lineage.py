"""add model parent lineage

Revision ID: 20260207_0002
Revises: 20260207_0001
Create Date: 2026-02-07 20:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260207_0002"
down_revision = "20260207_0001"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return table_name in _inspector().get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(item["name"] == column_name for item in _inspector().get_columns(table_name))


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(item["name"] == index_name for item in _inspector().get_indexes(table_name))


def upgrade() -> None:
    if _has_table("model") and not _has_column("model", "parent_model_id"):
        op.add_column("model", sa.Column("parent_model_id", sa.Uuid(), sa.ForeignKey("model.id"), nullable=True))

    if _has_table("model") and not _has_index("model", "ix_model_parent_model_id"):
        op.create_index("ix_model_parent_model_id", "model", ["parent_model_id"], unique=False)


def downgrade() -> None:
    if _has_table("model") and _has_index("model", "ix_model_parent_model_id"):
        op.drop_index("ix_model_parent_model_id", table_name="model")
    if _has_table("model") and _has_column("model", "parent_model_id"):
        op.drop_column("model", "parent_model_id")
