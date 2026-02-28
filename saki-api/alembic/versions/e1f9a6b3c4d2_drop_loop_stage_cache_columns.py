"""drop_loop_stage_cache_columns

Revision ID: e1f9a6b3c4d2
Revises: d6f0a8a1c2bf
Create Date: 2026-02-28 01:20:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "e1f9a6b3c4d2"
down_revision = "d6f0a8a1c2bf"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns(table)}
    return column in columns


def _has_index(table: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    indexes = {item["name"] for item in inspector.get_indexes(table)}
    return index_name in indexes


def upgrade() -> None:
    if _has_index("loop", op.f("ix_loop_stage")):
        op.drop_index(op.f("ix_loop_stage"), table_name="loop")

    if _has_column("loop", "stage_meta"):
        op.drop_column("loop", "stage_meta")
    if _has_column("loop", "stage"):
        op.drop_column("loop", "stage")

    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS loopstage")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name

    if dialect == "postgresql":
        loopstage_enum = postgresql.ENUM(
            "SNAPSHOT_REQUIRED",
            "LABEL_GAP_REQUIRED",
            "READY_TO_START",
            "RUNNING_ROUND",
            "WAITING_ROUND_LABEL",
            "READY_TO_CONFIRM",
            "COMPLETED",
            "STOPPED",
            "FAILED",
            "FAILED_RETRYABLE",
            name="loopstage",
        )
        loopstage_enum.create(op.get_bind(), checkfirst=True)
        stage_column_type = loopstage_enum
        stage_meta_default = sa.text("'{}'::jsonb")
    else:
        stage_column_type = sa.String(length=64)
        stage_meta_default = sa.text("'{}'")

    op.add_column(
        "loop",
        sa.Column(
            "stage",
            stage_column_type,
            nullable=False,
            server_default=sa.text("'SNAPSHOT_REQUIRED'"),
        ),
    )
    op.add_column(
        "loop",
        sa.Column(
            "stage_meta",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
            server_default=stage_meta_default,
        ),
    )
    op.create_index(op.f("ix_loop_stage"), "loop", ["stage"], unique=False)
    op.alter_column("loop", "stage", server_default=None)
    op.alter_column("loop", "stage_meta", server_default=None)

