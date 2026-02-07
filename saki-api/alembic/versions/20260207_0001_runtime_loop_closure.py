"""runtime loop closure schema expansion

Revision ID: 20260207_0001
Revises:
Create Date: 2026-02-07 17:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260207_0001"
down_revision = None
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return table_name in _inspector().get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(item["name"] == column_name for item in _inspector().get_columns(table_name))


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(item["name"] == index_name for item in _inspector().get_indexes(table_name))


def _add_column_if_missing(table_name: str, column_name: str, column: sa.Column) -> None:
    if _has_table(table_name) and not _has_column(table_name, column_name):
        op.add_column(table_name, column)


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str], unique: bool = False) -> None:
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _create_loop_round_table() -> None:
    if _has_table("loop_round"):
        return
    op.create_table(
        "loop_round",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("loop_id", sa.Uuid(), sa.ForeignKey("loop.id"), nullable=False),
        sa.Column("round_index", sa.Integer(), nullable=False),
        sa.Column("source_commit_id", sa.Uuid(), sa.ForeignKey("commit.id"), nullable=False),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("job.id"), nullable=True),
        sa.Column("annotation_batch_id", sa.Uuid(), sa.ForeignKey("annotation_batch.id"), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'training'")),
        sa.Column("metrics", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("selected_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("labeled_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
    )
    _create_index_if_missing("ix_loop_round_loop_id", "loop_round", ["loop_id"])
    _create_index_if_missing("ix_loop_round_round_index", "loop_round", ["round_index"])
    _create_index_if_missing("ix_loop_round_status", "loop_round", ["status"])
    _create_index_if_missing("ix_loop_round_job_id", "loop_round", ["job_id"])
    _create_index_if_missing("ix_loop_round_annotation_batch_id", "loop_round", ["annotation_batch_id"])


def _create_annotation_batch_tables() -> None:
    if not _has_table("annotation_batch"):
        op.create_table(
            "annotation_batch",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("project_id", sa.Uuid(), sa.ForeignKey("project.id"), nullable=False),
            sa.Column("loop_id", sa.Uuid(), sa.ForeignKey("loop.id"), nullable=False),
            sa.Column("job_id", sa.Uuid(), sa.ForeignKey("job.id"), nullable=False),
            sa.Column("round_index", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'open'")),
            sa.Column("total_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("annotated_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
            sa.Column("meta", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        )
    _create_index_if_missing("ix_annotation_batch_project_id", "annotation_batch", ["project_id"])
    _create_index_if_missing("ix_annotation_batch_loop_id", "annotation_batch", ["loop_id"])
    _create_index_if_missing("ix_annotation_batch_job_id", "annotation_batch", ["job_id"])
    _create_index_if_missing("ix_annotation_batch_round_index", "annotation_batch", ["round_index"])
    _create_index_if_missing("ix_annotation_batch_status", "annotation_batch", ["status"])

    if not _has_table("annotation_batch_item"):
        op.create_table(
            "annotation_batch_item",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("batch_id", sa.Uuid(), sa.ForeignKey("annotation_batch.id"), nullable=False),
            sa.Column("sample_id", sa.Uuid(), sa.ForeignKey("sample.id"), nullable=False),
            sa.Column("rank", sa.Integer(), nullable=False),
            sa.Column("score", sa.Float(), nullable=False),
            sa.Column("reason", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("prediction_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("is_annotated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("annotated_at", sa.DateTime(), nullable=True),
            sa.Column("annotation_commit_id", sa.Uuid(), sa.ForeignKey("commit.id"), nullable=True),
        )
    _create_index_if_missing("ix_annotation_batch_item_batch_id", "annotation_batch_item", ["batch_id"])
    _create_index_if_missing("ix_annotation_batch_item_sample_id", "annotation_batch_item", ["sample_id"])
    _create_index_if_missing("ix_annotation_batch_item_rank", "annotation_batch_item", ["rank"])
    _create_index_if_missing("ix_annotation_batch_item_score", "annotation_batch_item", ["score"])
    _create_index_if_missing("ix_annotation_batch_item_is_annotated", "annotation_batch_item", ["is_annotated"])


def upgrade() -> None:
    _add_column_if_missing(
        "loop",
        "status",
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'draft'")),
    )
    _add_column_if_missing(
        "loop",
        "max_rounds",
        sa.Column("max_rounds", sa.Integer(), nullable=False, server_default=sa.text("5")),
    )
    _add_column_if_missing(
        "loop",
        "query_batch_size",
        sa.Column("query_batch_size", sa.Integer(), nullable=False, server_default=sa.text("200")),
    )
    _add_column_if_missing(
        "loop",
        "min_seed_labeled",
        sa.Column("min_seed_labeled", sa.Integer(), nullable=False, server_default=sa.text("100")),
    )
    _add_column_if_missing(
        "loop",
        "min_new_labels_per_round",
        sa.Column("min_new_labels_per_round", sa.Integer(), nullable=False, server_default=sa.text("120")),
    )
    _add_column_if_missing(
        "loop",
        "stop_patience_rounds",
        sa.Column("stop_patience_rounds", sa.Integer(), nullable=False, server_default=sa.text("2")),
    )
    _add_column_if_missing(
        "loop",
        "stop_min_gain",
        sa.Column("stop_min_gain", sa.Float(), nullable=False, server_default=sa.text("0.002")),
    )
    _add_column_if_missing(
        "loop",
        "auto_register_model",
        sa.Column("auto_register_model", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    _add_column_if_missing("loop", "last_job_id", sa.Column("last_job_id", sa.Uuid(), nullable=True))
    _add_column_if_missing("loop", "latest_model_id", sa.Column("latest_model_id", sa.Uuid(), nullable=True))
    _add_column_if_missing("loop", "last_error", sa.Column("last_error", sa.String(length=4000), nullable=True))
    _create_index_if_missing("ix_loop_status", "loop", ["status"])
    _create_index_if_missing("ix_loop_last_job_id", "loop", ["last_job_id"])
    _create_index_if_missing("ix_loop_latest_model_id", "loop", ["latest_model_id"])

    _add_column_if_missing("job", "round_index", sa.Column("round_index", sa.Integer(), nullable=False, server_default=sa.text("0")))
    _add_column_if_missing("job", "strategy_params", sa.Column("strategy_params", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    _add_column_if_missing("job", "model_id", sa.Column("model_id", sa.Uuid(), nullable=True))
    _create_index_if_missing("ix_job_round_index", "job", ["round_index"])
    _create_index_if_missing("ix_job_model_id", "job", ["model_id"])

    _add_column_if_missing("model", "source_commit_id", sa.Column("source_commit_id", sa.Uuid(), nullable=True))
    _add_column_if_missing("model", "plugin_id", sa.Column("plugin_id", sa.String(length=255), nullable=False, server_default=sa.text("''")))
    _add_column_if_missing("model", "model_arch", sa.Column("model_arch", sa.String(length=255), nullable=False, server_default=sa.text("''")))
    _add_column_if_missing("model", "metrics", sa.Column("metrics", sa.JSON(), nullable=True))
    _add_column_if_missing("model", "artifacts", sa.Column("artifacts", sa.JSON(), nullable=True))
    _add_column_if_missing("model", "promoted_at", sa.Column("promoted_at", sa.DateTime(), nullable=True))
    _add_column_if_missing("model", "created_by", sa.Column("created_by", sa.Uuid(), nullable=True))
    _create_index_if_missing("ix_model_source_commit_id", "model", ["source_commit_id"])
    _create_index_if_missing("ix_model_plugin_id", "model", ["plugin_id"])
    _create_index_if_missing("ix_model_model_arch", "model", ["model_arch"])

    _create_annotation_batch_tables()
    _create_loop_round_table()


def downgrade() -> None:
    if _has_table("loop_round"):
        op.drop_table("loop_round")
    if _has_table("annotation_batch_item"):
        op.drop_table("annotation_batch_item")
    if _has_table("annotation_batch"):
        op.drop_table("annotation_batch")

    for table_name, column_name in [
        ("model", "created_by"),
        ("model", "promoted_at"),
        ("model", "artifacts"),
        ("model", "metrics"),
        ("model", "model_arch"),
        ("model", "plugin_id"),
        ("model", "source_commit_id"),
        ("job", "model_id"),
        ("job", "strategy_params"),
        ("job", "round_index"),
        ("loop", "last_error"),
        ("loop", "latest_model_id"),
        ("loop", "last_job_id"),
        ("loop", "auto_register_model"),
        ("loop", "stop_min_gain"),
        ("loop", "stop_patience_rounds"),
        ("loop", "min_new_labels_per_round"),
        ("loop", "min_seed_labeled"),
        ("loop", "query_batch_size"),
        ("loop", "max_rounds"),
        ("loop", "status"),
    ]:
        if _has_column(table_name, column_name):
            op.drop_column(table_name, column_name)
