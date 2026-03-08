"""add_task_result_ready_at

Revision ID: 7d2f4a1b9c3e
Revises: 4b2b8a0ce9b1
Create Date: 2026-03-09 00:00:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7d2f4a1b9c3e"
down_revision = "4b2b8a0ce9b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task",
        sa.Column("result_ready_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("task", "result_ready_at")
