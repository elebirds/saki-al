"""fix runtime event ts seconds

Revision ID: d6f0a8a1c2bf
Revises: c91c6d3e4f2b
Create Date: 2026-02-27 19:35:00.000000

"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "d6f0a8a1c2bf"
down_revision = "c91c6d3e4f2b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE step_event
        SET ts = to_timestamp(EXTRACT(EPOCH FROM ts) * 1000.0)
        WHERE ts >= TIMESTAMPTZ '1970-01-02 00:00:00+00'
          AND ts < TIMESTAMPTZ '2001-01-01 00:00:00+00'
        """
    )
    op.execute(
        """
        UPDATE step_metric_point
        SET ts = to_timestamp(EXTRACT(EPOCH FROM ts) * 1000.0)
        WHERE ts >= TIMESTAMPTZ '1970-01-02 00:00:00+00'
          AND ts < TIMESTAMPTZ '2001-01-01 00:00:00+00'
        """
    )


def downgrade() -> None:
    # Non-reversible data correction.
    pass
