"""switch_model_source_step_to_task

Revision ID: c6f0d1e2f3a4
Revises: 5d6f7a8b9c10
Create Date: 2026-03-06 20:55:00.000000

"""
from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "c6f0d1e2f3a4"
down_revision = "5d6f7a8b9c10"
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
      AND table_name = 'model'
      AND column_name = 'source_step_id'
  ) AND NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'model'
      AND column_name = 'source_task_id'
  ) THEN
    ALTER TABLE public.model RENAME COLUMN source_step_id TO source_task_id;
  END IF;
END
$$;
"""
    )
    op.execute(
        """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'fk_model_source_step_id_step'
  ) THEN
    ALTER TABLE public.model DROP CONSTRAINT fk_model_source_step_id_step;
  END IF;
END
$$;
"""
    )
    op.execute("ALTER INDEX IF EXISTS ix_model_source_step_id RENAME TO ix_model_source_task_id")
    op.execute("CREATE INDEX IF NOT EXISTS ix_model_source_task_id ON public.model(source_task_id)")
    op.execute(
        """
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'fk_model_source_task_id_task'
  ) THEN
    ALTER TABLE public.model
      ADD CONSTRAINT fk_model_source_task_id_task
      FOREIGN KEY (source_task_id) REFERENCES public.task(id);
  END IF;
END
$$;
"""
    )


def downgrade() -> None:
    op.execute(
        """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'fk_model_source_task_id_task'
  ) THEN
    ALTER TABLE public.model DROP CONSTRAINT fk_model_source_task_id_task;
  END IF;
END
$$;
"""
    )
    op.execute(
        """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'model'
      AND column_name = 'source_task_id'
  ) AND NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'model'
      AND column_name = 'source_step_id'
  ) THEN
    ALTER TABLE public.model RENAME COLUMN source_task_id TO source_step_id;
  END IF;
END
$$;
"""
    )
    op.execute("ALTER INDEX IF EXISTS ix_model_source_task_id RENAME TO ix_model_source_step_id")
    op.execute("CREATE INDEX IF NOT EXISTS ix_model_source_step_id ON public.model(source_step_id)")
    op.execute(
        """
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'fk_model_source_step_id_step'
  ) THEN
    ALTER TABLE public.model
      ADD CONSTRAINT fk_model_source_step_id_step
      FOREIGN KEY (source_step_id) REFERENCES public.step(id);
  END IF;
END
$$;
"""
    )
