"""enforce_step_task_not_null

Revision ID: 7d2f1a9c4b6e
Revises: c6f0d1e2f3a4
Create Date: 2026-03-06 22:05:00.000000

"""
from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "7d2f1a9c4b6e"
down_revision = "c6f0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM public.step
    WHERE task_id IS NULL
  ) THEN
    RAISE EXCEPTION 'step.task_id contains NULL rows; clean dirty data before hard-cut migration';
  END IF;
END
$$;
"""
    )
    op.execute("ALTER TABLE public.step ALTER COLUMN task_id SET NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE public.step ALTER COLUMN task_id DROP NOT NULL")
