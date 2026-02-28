"""loop_lifecycle_hard_cut

Revision ID: bb2d8f1a4c7e
Revises: a9d4e2f7b1c3
Create Date: 2026-02-28 23:58:00.000000

"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "bb2d8f1a4c7e"
down_revision = "a9d4e2f7b1c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE loop RENAME COLUMN status TO lifecycle")
    op.execute("ALTER TYPE loopstatus RENAME TO looplifecycle")
    op.execute("ALTER INDEX IF EXISTS ix_loop_status RENAME TO ix_loop_lifecycle")


def downgrade() -> None:
    op.execute("ALTER INDEX IF EXISTS ix_loop_lifecycle RENAME TO ix_loop_status")
    op.execute("ALTER TYPE looplifecycle RENAME TO loopstatus")
    op.execute("ALTER TABLE loop RENAME COLUMN lifecycle TO status")
