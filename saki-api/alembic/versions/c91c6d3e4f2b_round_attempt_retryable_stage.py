"""round_attempt_retryable_stage

Revision ID: c91c6d3e4f2b
Revises: b7f3a7d5c9c1
Create Date: 2026-02-27 09:40:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c91c6d3e4f2b"
down_revision = "b7f3a7d5c9c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE loopstage ADD VALUE IF NOT EXISTS 'FAILED_RETRYABLE'")

    op.add_column(
        "round",
        sa.Column("attempt_index", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column("round", sa.Column("retry_of_round_id", sa.Uuid(), nullable=True))
    op.add_column("round", sa.Column("retry_reason", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_round_retry_of_round_id_round",
        "round",
        "round",
        ["retry_of_round_id"],
        ["id"],
    )
    op.create_index(op.f("ix_round_attempt_index"), "round", ["attempt_index"], unique=False)
    op.create_index(op.f("ix_round_retry_of_round_id"), "round", ["retry_of_round_id"], unique=False)

    op.execute("UPDATE round SET attempt_index = 1 WHERE attempt_index IS NULL")
    op.alter_column("round", "attempt_index", server_default=None)

    op.drop_constraint("uq_round_loop_round", "round", type_="unique")
    op.create_unique_constraint(
        "uq_round_loop_round_attempt",
        "round",
        ["loop_id", "round_index", "attempt_index"],
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_round_loop_round_attempt
        ON round (loop_id, round_index DESC, attempt_index DESC, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_round_loop_round_attempt")
    op.drop_constraint("uq_round_loop_round_attempt", "round", type_="unique")
    op.create_unique_constraint("uq_round_loop_round", "round", ["loop_id", "round_index"])

    op.drop_index(op.f("ix_round_retry_of_round_id"), table_name="round")
    op.drop_index(op.f("ix_round_attempt_index"), table_name="round")
    op.drop_constraint("fk_round_retry_of_round_id_round", "round", type_="foreignkey")
    op.drop_column("round", "retry_reason")
    op.drop_column("round", "retry_of_round_id")
    op.drop_column("round", "attempt_index")
