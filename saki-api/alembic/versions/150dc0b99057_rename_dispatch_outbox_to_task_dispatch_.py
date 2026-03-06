"""rename_dispatch_outbox_to_task_dispatch_outbox

Revision ID: 150dc0b99057
Revises: 51cf38b5a3bc
Create Date: 2026-03-06 17:04:46.037606

"""
from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = '150dc0b99057'
down_revision = '51cf38b5a3bc'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
DO $$
BEGIN
  IF to_regclass('public.dispatch_outbox') IS NOT NULL
     AND to_regclass('public.task_dispatch_outbox') IS NULL THEN
    ALTER TABLE public.dispatch_outbox RENAME TO task_dispatch_outbox;
  END IF;
END
$$;
"""
    )
    op.execute("ALTER INDEX IF EXISTS ix_dispatch_outbox_request_id RENAME TO ix_task_dispatch_outbox_request_id")
    op.execute(
        "ALTER INDEX IF EXISTS ix_dispatch_outbox_status_next_attempt_at "
        "RENAME TO ix_task_dispatch_outbox_status_next_attempt_at"
    )
    op.execute("ALTER INDEX IF EXISTS ix_dispatch_outbox_task_id RENAME TO ix_task_dispatch_outbox_task_id")
    op.execute(
        """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'dispatch_outbox_pkey'
  ) THEN
    ALTER TABLE public.task_dispatch_outbox
      RENAME CONSTRAINT dispatch_outbox_pkey TO task_dispatch_outbox_pkey;
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
    SELECT 1 FROM pg_constraint WHERE conname = 'dispatch_outbox_task_id_fkey'
  ) THEN
    ALTER TABLE public.task_dispatch_outbox
      RENAME CONSTRAINT dispatch_outbox_task_id_fkey TO task_dispatch_outbox_task_id_fkey;
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
  IF to_regclass('public.task_dispatch_outbox') IS NOT NULL
     AND to_regclass('public.dispatch_outbox') IS NULL THEN
    ALTER TABLE public.task_dispatch_outbox RENAME TO dispatch_outbox;
  END IF;
END
$$;
"""
    )
    op.execute("ALTER INDEX IF EXISTS ix_task_dispatch_outbox_request_id RENAME TO ix_dispatch_outbox_request_id")
    op.execute(
        "ALTER INDEX IF EXISTS ix_task_dispatch_outbox_status_next_attempt_at "
        "RENAME TO ix_dispatch_outbox_status_next_attempt_at"
    )
    op.execute("ALTER INDEX IF EXISTS ix_task_dispatch_outbox_task_id RENAME TO ix_dispatch_outbox_task_id")
    op.execute(
        """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'task_dispatch_outbox_pkey'
  ) THEN
    ALTER TABLE public.dispatch_outbox
      RENAME CONSTRAINT task_dispatch_outbox_pkey TO dispatch_outbox_pkey;
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
    SELECT 1 FROM pg_constraint WHERE conname = 'task_dispatch_outbox_task_id_fkey'
  ) THEN
    ALTER TABLE public.dispatch_outbox
      RENAME CONSTRAINT task_dispatch_outbox_task_id_fkey TO dispatch_outbox_task_id_fkey;
  END IF;
END
$$;
"""
    )
