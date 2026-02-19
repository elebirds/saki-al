"""add_dataset_is_public

Revision ID: 1c2d6f9de7b1
Revises: 09af1c227e1d
Create Date: 2026-02-19 23:50:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "1c2d6f9de7b1"
down_revision = "09af1c227e1d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dataset",
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("dataset", "is_public")
