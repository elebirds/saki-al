"""fix timezone aware datetimes

Revision ID: a00e4ff62324
Revises: 4d7c24d18ff4
Create Date: 2026-02-26 18:51:24.050946

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a00e4ff62324"
down_revision = "4d7c24d18ff4"
branch_labels = None
depends_on = None


DATETIME_COLUMNS: list[tuple[str, str, bool]] = [
    ("annotation", "created_at", False),
    ("annotation", "updated_at", False),
    ("annotation_draft", "created_at", False),
    ("annotation_draft", "updated_at", False),
    ("asset", "created_at", False),
    ("asset", "updated_at", False),
    ("audit_log", "created_at", False),
    ("audit_log", "updated_at", False),
    ("branch", "created_at", False),
    ("branch", "updated_at", False),
    ("commit", "created_at", False),
    ("commit", "updated_at", False),
    ("dataset", "created_at", False),
    ("dataset", "updated_at", False),
    ("dispatch_outbox", "created_at", False),
    ("dispatch_outbox", "updated_at", False),
    ("dispatch_outbox", "next_attempt_at", False),
    ("dispatch_outbox", "locked_at", True),
    ("dispatch_outbox", "sent_at", True),
    ("import_task", "created_at", False),
    ("import_task", "updated_at", False),
    ("import_task", "started_at", True),
    ("import_task", "finished_at", True),
    ("import_task_event", "ts", False),
    ("label", "created_at", False),
    ("label", "updated_at", False),
    ("loop", "created_at", False),
    ("loop", "updated_at", False),
    ("model", "created_at", False),
    ("model", "updated_at", False),
    ("model", "promoted_at", True),
    ("project", "created_at", False),
    ("project", "updated_at", False),
    ("resource_member", "created_at", False),
    ("resource_member", "updated_at", False),
    ("role", "created_at", False),
    ("role", "updated_at", False),
    ("role_permission", "created_at", False),
    ("role_permission", "updated_at", False),
    ("round", "created_at", False),
    ("round", "updated_at", False),
    ("round", "started_at", True),
    ("round", "ended_at", True),
    ("runtime_command_log", "created_at", False),
    ("runtime_command_log", "updated_at", False),
    ("runtime_executor", "created_at", False),
    ("runtime_executor", "updated_at", False),
    ("runtime_executor", "last_seen_at", True),
    ("runtime_executor_stats", "created_at", False),
    ("runtime_executor_stats", "updated_at", False),
    ("runtime_executor_stats", "ts", False),
    ("sample", "created_at", False),
    ("sample", "updated_at", False),
    ("step", "created_at", False),
    ("step", "updated_at", False),
    ("step", "started_at", True),
    ("step", "ended_at", True),
    ("step_candidate_item", "created_at", False),
    ("step_candidate_item", "updated_at", False),
    ("step_event", "created_at", False),
    ("step_event", "updated_at", False),
    ("step_event", "ts", False),
    ("step_metric_point", "created_at", False),
    ("step_metric_point", "updated_at", False),
    ("step_metric_point", "ts", False),
    ("system_setting", "created_at", False),
    ("system_setting", "updated_at", False),
    ("user", "created_at", False),
    ("user", "updated_at", False),
    ("user_system_role", "created_at", False),
    ("user_system_role", "updated_at", False),
    ("user_system_role", "expires_at", True),
]


def _to_timestamptz(table_name: str, column_name: str, nullable: bool) -> None:
    op.alter_column(
        table_name,
        column_name,
        existing_type=sa.DateTime(timezone=False),
        type_=sa.DateTime(timezone=True),
        existing_nullable=nullable,
        postgresql_using=f"{column_name} AT TIME ZONE 'UTC'",
    )


def _to_timestamp(table_name: str, column_name: str, nullable: bool) -> None:
    op.alter_column(
        table_name,
        column_name,
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(timezone=False),
        existing_nullable=nullable,
        postgresql_using=f"{column_name} AT TIME ZONE 'UTC'",
    )


def upgrade() -> None:
    for table_name, column_name, nullable in DATETIME_COLUMNS:
        _to_timestamptz(table_name, column_name, nullable)


def downgrade() -> None:
    for table_name, column_name, nullable in reversed(DATETIME_COLUMNS):
        _to_timestamp(table_name, column_name, nullable)
