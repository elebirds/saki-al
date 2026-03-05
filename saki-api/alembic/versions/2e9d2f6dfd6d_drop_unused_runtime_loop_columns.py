"""drop_unused_runtime_loop_columns

Revision ID: 2e9d2f6dfd6d
Revises: 8f63c92e3b1e
Create Date: 2026-03-05 19:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "2e9d2f6dfd6d"
down_revision: Union[str, Sequence[str], None] = "8f63c92e3b1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("round_confirmed_commit_id_fkey", "round", type_="foreignkey")
    op.drop_constraint("round_output_commit_id_fkey", "round", type_="foreignkey")
    op.drop_constraint("step_output_commit_id_fkey", "step", type_="foreignkey")

    op.drop_index("ix_round_round_type", table_name="round")
    op.drop_index("ix_runtime_command_log_command_type", table_name="runtime_command_log")
    op.drop_index("ix_runtime_command_log_resource_id", table_name="runtime_command_log")
    op.drop_index("ix_step_dispatch_request_id", table_name="step")
    op.drop_index("ix_step_output_commit_id", table_name="step")

    op.drop_column("loop", "phase_meta")
    op.drop_column("loop", "min_seed_labeled")
    op.drop_column("loop", "stop_patience_rounds")
    op.drop_column("loop", "stop_min_gain")
    op.drop_column("loop", "auto_register_model")

    op.drop_column("round", "round_type")
    op.drop_column("round", "retry_count")
    op.drop_column("round", "strategy_params")
    op.drop_column("round", "output_commit_id")
    op.drop_column("round", "confirmed_commit_id")

    op.drop_column("step", "dispatch_request_id")
    op.drop_column("step", "output_commit_id")
    op.drop_column("step_event", "request_id")

    op.drop_column("runtime_command_log", "command_type")
    op.drop_column("runtime_command_log", "resource_id")


def downgrade() -> None:
    op.add_column(
        "runtime_command_log",
        sa.Column("resource_id", sa.String(length=128), nullable=False, server_default=sa.text("''")),
    )
    op.add_column(
        "runtime_command_log",
        sa.Column("command_type", sa.String(length=64), nullable=False, server_default=sa.text("'unknown'")),
    )

    op.add_column("step_event", sa.Column("request_id", sa.String(length=128), nullable=True))

    op.add_column("step", sa.Column("output_commit_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("step", sa.Column("dispatch_request_id", sa.String(length=128), nullable=True))

    op.add_column("round", sa.Column("confirmed_commit_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("round", sa.Column("output_commit_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("round", sa.Column("strategy_params", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("round", sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column(
        "round",
        sa.Column("round_type", sa.String(length=255), nullable=False, server_default=sa.text("'loop_round'")),
    )

    op.add_column(
        "loop",
        sa.Column("auto_register_model", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "loop",
        sa.Column("stop_min_gain", sa.Float(precision=53), nullable=False, server_default=sa.text("0.002")),
    )
    op.add_column(
        "loop",
        sa.Column("stop_patience_rounds", sa.Integer(), nullable=False, server_default=sa.text("2")),
    )
    op.add_column(
        "loop",
        sa.Column("min_seed_labeled", sa.Integer(), nullable=False, server_default=sa.text("100")),
    )
    op.add_column("loop", sa.Column("phase_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.create_index("ix_round_round_type", "round", ["round_type"], unique=False)
    op.create_index("ix_runtime_command_log_command_type", "runtime_command_log", ["command_type"], unique=False)
    op.create_index("ix_runtime_command_log_resource_id", "runtime_command_log", ["resource_id"], unique=False)
    op.create_index("ix_step_dispatch_request_id", "step", ["dispatch_request_id"], unique=False)
    op.create_index("ix_step_output_commit_id", "step", ["output_commit_id"], unique=False)

    op.create_foreign_key(
        "round_confirmed_commit_id_fkey",
        "round",
        "commit",
        ["confirmed_commit_id"],
        ["id"],
    )
    op.create_foreign_key(
        "round_output_commit_id_fkey",
        "round",
        "commit",
        ["output_commit_id"],
        ["id"],
    )
    op.create_foreign_key(
        "step_output_commit_id_fkey",
        "step",
        "commit",
        ["output_commit_id"],
        ["id"],
    )
