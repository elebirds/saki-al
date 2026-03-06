"""drop_predict_from_steptype

Revision ID: 51cf38b5a3bc
Revises: fbb9e3731c2d
Create Date: 2026-03-06 17:02:35.373479

"""
from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = '51cf38b5a3bc'
down_revision = 'fbb9e3731c2d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM step
    WHERE step_type::text = 'PREDICT'
  ) THEN
    RAISE EXCEPTION 'step.step_type still contains PREDICT rows, cleanup is required before upgrade';
  END IF;
END
$$;
"""
    )
    op.execute("ALTER TYPE steptype RENAME TO steptype_old")
    op.execute("CREATE TYPE steptype AS ENUM ('TRAIN', 'EVAL', 'SCORE', 'SELECT', 'CUSTOM')")
    op.execute("ALTER TABLE step ALTER COLUMN step_type TYPE steptype USING step_type::text::steptype")
    op.execute("DROP TYPE steptype_old")


def downgrade() -> None:
    op.execute("ALTER TYPE steptype RENAME TO steptype_old")
    op.execute("CREATE TYPE steptype AS ENUM ('TRAIN', 'EVAL', 'SCORE', 'SELECT', 'PREDICT', 'CUSTOM')")
    op.execute("ALTER TABLE step ALTER COLUMN step_type TYPE steptype USING step_type::text::steptype")
    op.execute("DROP TYPE steptype_old")
