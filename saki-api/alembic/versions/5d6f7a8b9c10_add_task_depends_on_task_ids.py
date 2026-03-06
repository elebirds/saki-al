"""add_task_depends_on_task_ids

Revision ID: 5d6f7a8b9c10
Revises: b75d3661522b
Create Date: 2026-03-06 20:40:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "5d6f7a8b9c10"
down_revision = "b75d3661522b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task",
        sa.Column(
            "depends_on_task_ids",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("task", "depends_on_task_ids")
