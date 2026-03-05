"""prediction_task_hardcut

Revision ID: 4b3f2d1f7c9a
Revises: 2e9d2f6dfd6d
Create Date: 2026-03-06 15:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "4b3f2d1f7c9a"
down_revision: Union[str, Sequence[str], None] = "2e9d2f6dfd6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    task_kind_enum = sa.Enum("STEP", "PREDICTION", name="taskkind")
    task_type_enum = sa.Enum("TRAIN", "EVAL", "SCORE", "SELECT", "PREDICT", "CUSTOM", name="tasktype")
    task_status_enum = sa.Enum(
        "PENDING",
        "READY",
        "DISPATCHING",
        "SYNCING_ENV",
        "PROBING_RUNTIME",
        "BINDING_DEVICE",
        "RUNNING",
        "RETRYING",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        "SKIPPED",
        name="taskstatus",
    )
    bind = op.get_bind()
    task_kind_enum.create(bind, checkfirst=True)
    task_type_enum.create(bind, checkfirst=True)
    task_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "task",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("kind", task_kind_enum, nullable=False),
        sa.Column("task_type", task_type_enum, nullable=False),
        sa.Column("status", task_status_enum, nullable=False),
        sa.Column("plugin_id", sa.String(length=255), nullable=False),
        sa.Column("input_commit_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_params", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("assigned_executor_id", sa.String(length=255), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=4000), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.ForeignKeyConstraint(["input_commit_id"], ["commit.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_project_id", "task", ["project_id"], unique=False)
    op.create_index("ix_task_kind", "task", ["kind"], unique=False)
    op.create_index("ix_task_task_type", "task", ["task_type"], unique=False)
    op.create_index("ix_task_status", "task", ["status"], unique=False)
    op.create_index("ix_task_plugin_id", "task", ["plugin_id"], unique=False)
    op.create_index("ix_task_input_commit_id", "task", ["input_commit_id"], unique=False)
    op.create_index("ix_task_assigned_executor_id", "task", ["assigned_executor_id"], unique=False)

    op.add_column("step", sa.Column("task_id", sa.Uuid(), nullable=True))
    op.create_index("ix_step_task_id", "step", ["task_id"], unique=True)
    op.create_foreign_key("fk_step_task_id_task", "step", "task", ["task_id"], ["id"])

    # Hard cut: clear legacy prediction artifacts before schema rename.
    op.execute("DELETE FROM prediction_item")
    op.execute("DELETE FROM prediction_set_binding")
    op.execute("DELETE FROM prediction_set")

    op.rename_table("prediction_set", "prediction")
    op.rename_table("prediction_set_binding", "prediction_binding")

    op.add_column("prediction", sa.Column("task_id", sa.Uuid(), nullable=True))
    op.create_index("ix_prediction_task_id", "prediction", ["task_id"], unique=True)
    op.create_foreign_key("fk_prediction_task_id_task", "prediction", "task", ["task_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_prediction_task_id_task", "prediction", type_="foreignkey")
    op.drop_index("ix_prediction_task_id", table_name="prediction")
    op.drop_column("prediction", "task_id")
    op.rename_table("prediction_binding", "prediction_set_binding")
    op.rename_table("prediction", "prediction_set")

    op.drop_constraint("fk_step_task_id_task", "step", type_="foreignkey")
    op.drop_index("ix_step_task_id", table_name="step")
    op.drop_column("step", "task_id")

    op.drop_index("ix_task_assigned_executor_id", table_name="task")
    op.drop_index("ix_task_input_commit_id", table_name="task")
    op.drop_index("ix_task_plugin_id", table_name="task")
    op.drop_index("ix_task_status", table_name="task")
    op.drop_index("ix_task_task_type", table_name="task")
    op.drop_index("ix_task_kind", table_name="task")
    op.drop_index("ix_task_project_id", table_name="task")
    op.drop_table("task")

    bind = op.get_bind()
    sa.Enum(name="taskstatus").drop(bind, checkfirst=True)
    sa.Enum(name="tasktype").drop(bind, checkfirst=True)
    sa.Enum(name="taskkind").drop(bind, checkfirst=True)
