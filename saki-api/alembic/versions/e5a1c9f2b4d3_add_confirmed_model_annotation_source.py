"""add_confirmed_model_annotation_source

Revision ID: e5a1c9f2b4d3
Revises: c3d5e7f9a1b2
Create Date: 2026-03-02 12:30:00.000000

"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "e5a1c9f2b4d3"
down_revision = "c3d5e7f9a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE annotationsource ADD VALUE IF NOT EXISTS 'CONFIRMED_MODEL'")


def downgrade() -> None:
    # PostgreSQL enum value deletion is irreversible in-place; keep downgrade as no-op.
    pass
