"""runtime_execution_identity_and_pause

Revision ID: 9a1f2d7c4b6e
Revises: 7d2f4a1b9c3e
Create Date: 2026-03-09 23:30:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "9a1f2d7c4b6e"
down_revision = "7d2f4a1b9c3e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE looplifecycle ADD VALUE IF NOT EXISTS 'PAUSING'")
    pause_reason = postgresql.ENUM("USER", "MAINTENANCE", name="looppausereason")
    pause_reason.create(op.get_bind(), checkfirst=True)

    op.add_column("loop", sa.Column("pause_reason", pause_reason, nullable=True))
    op.create_index(op.f("ix_loop_pause_reason"), "loop", ["pause_reason"], unique=False)

    op.add_column("task", sa.Column("current_execution_id", sa.Uuid(), nullable=True))
    op.add_column(
        "task",
        sa.Column(
            "warnings",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
    )
    op.execute("UPDATE task SET current_execution_id = id WHERE current_execution_id IS NULL")
    op.execute("UPDATE task SET warnings = '[]'::jsonb WHERE warnings IS NULL")
    op.alter_column("task", "current_execution_id", nullable=False)
    op.create_index(op.f("ix_task_current_execution_id"), "task", ["current_execution_id"], unique=False)

    op.add_column("task_event", sa.Column("execution_id", sa.Uuid(), nullable=True))
    op.execute("UPDATE task_event SET execution_id = task_id WHERE execution_id IS NULL")
    op.alter_column("task_event", "execution_id", nullable=False)
    op.create_index(op.f("ix_task_event_execution_id"), "task_event", ["execution_id"], unique=False)
    op.drop_constraint("uq_task_event_seq", "task_event", type_="unique")
    op.create_unique_constraint(
        "uq_task_event_execution_seq",
        "task_event",
        ["task_id", "execution_id", "seq"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_task_event_execution_seq", "task_event", type_="unique")
    op.create_unique_constraint("uq_task_event_seq", "task_event", ["task_id", "seq"])
    op.drop_index(op.f("ix_task_event_execution_id"), table_name="task_event")
    op.drop_column("task_event", "execution_id")

    op.drop_index(op.f("ix_task_current_execution_id"), table_name="task")
    op.drop_column("task", "warnings")
    op.drop_column("task", "current_execution_id")

    op.drop_index(op.f("ix_loop_pause_reason"), table_name="loop")
    op.drop_column("loop", "pause_reason")

    pause_reason = postgresql.ENUM("USER", "MAINTENANCE", name="looppausereason")
    pause_reason.drop(op.get_bind(), checkfirst=True)
