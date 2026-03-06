"""rename_runtime_executor_current_step_id_to_current_task_id

Revision ID: b75d3661522b
Revises: 150dc0b99057
Create Date: 2026-03-06 17:06:16.402957

"""
from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = 'b75d3661522b'
down_revision = '150dc0b99057'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'runtime_executor'
      AND column_name = 'current_step_id'
  ) AND NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'runtime_executor'
      AND column_name = 'current_task_id'
  ) THEN
    ALTER TABLE public.runtime_executor RENAME COLUMN current_step_id TO current_task_id;
  END IF;
END
$$;
"""
    )
    op.execute("ALTER INDEX IF EXISTS ix_runtime_executor_current_step_id RENAME TO ix_runtime_executor_current_task_id")


def downgrade() -> None:
    op.execute(
        """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'runtime_executor'
      AND column_name = 'current_task_id'
  ) AND NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'runtime_executor'
      AND column_name = 'current_step_id'
  ) THEN
    ALTER TABLE public.runtime_executor RENAME COLUMN current_task_id TO current_step_id;
  END IF;
END
$$;
"""
    )
    op.execute("ALTER INDEX IF EXISTS ix_runtime_executor_current_task_id RENAME TO ix_runtime_executor_current_step_id")
