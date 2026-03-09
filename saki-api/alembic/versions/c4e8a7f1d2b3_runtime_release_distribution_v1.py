"""runtime_release_distribution_v1

Revision ID: c4e8a7f1d2b3
Revises: 9a1f2d7c4b6e
Create Date: 2026-03-10 00:20:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "c4e8a7f1d2b3"
down_revision = "9a1f2d7c4b6e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "runtime_executor",
        sa.Column(
            "update_state",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
    )

    op.create_table(
        "runtime_release",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("component_type", sa.String(length=16), nullable=False),
        sa.Column("component_name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("format", sa.String(length=32), nullable=False),
        sa.Column(
            "manifest_json",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"], name="fk_runtime_release_asset_id"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_runtime_release_created_by"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runtime_release_asset_id", "runtime_release", ["asset_id"], unique=False)
    op.create_index("ix_runtime_release_component_name", "runtime_release", ["component_name"], unique=False)
    op.create_index("ix_runtime_release_component_type", "runtime_release", ["component_type"], unique=False)
    op.create_index(
        "ix_runtime_release_component_version",
        "runtime_release",
        ["component_type", "component_name", "version"],
        unique=True,
    )

    op.create_table(
        "runtime_desired_state",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("component_type", sa.String(length=16), nullable=False),
        sa.Column("component_name", sa.String(length=255), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["release_id"], ["runtime_release.id"], name="fk_runtime_desired_state_release_id"),
        sa.ForeignKeyConstraint(["updated_by"], ["user.id"], name="fk_runtime_desired_state_updated_by"),
        sa.PrimaryKeyConstraint("component_type", "component_name"),
    )
    op.create_index("ix_runtime_desired_state_release_id", "runtime_desired_state", ["release_id"], unique=False)

    op.create_table(
        "runtime_update_attempt",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("executor_id", sa.String(length=128), nullable=False),
        sa.Column("component_type", sa.String(length=16), nullable=False),
        sa.Column("component_name", sa.String(length=255), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("from_version", sa.String(length=64), nullable=False),
        sa.Column("target_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.String(length=4000), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rollback_detail", sa.String(length=4000), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runtime_update_attempt_executor_id", "runtime_update_attempt", ["executor_id"], unique=False)
    op.create_index("ix_runtime_update_attempt_request_id", "runtime_update_attempt", ["request_id"], unique=True)
    op.create_index("ix_runtime_update_attempt_started_at", "runtime_update_attempt", ["started_at"], unique=False)
    op.create_index("ix_runtime_update_attempt_status", "runtime_update_attempt", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_runtime_update_attempt_status", table_name="runtime_update_attempt")
    op.drop_index("ix_runtime_update_attempt_started_at", table_name="runtime_update_attempt")
    op.drop_index("ix_runtime_update_attempt_request_id", table_name="runtime_update_attempt")
    op.drop_index("ix_runtime_update_attempt_executor_id", table_name="runtime_update_attempt")
    op.drop_table("runtime_update_attempt")

    op.drop_index("ix_runtime_desired_state_release_id", table_name="runtime_desired_state")
    op.drop_table("runtime_desired_state")

    op.drop_index("ix_runtime_release_component_version", table_name="runtime_release")
    op.drop_index("ix_runtime_release_component_type", table_name="runtime_release")
    op.drop_index("ix_runtime_release_component_name", table_name="runtime_release")
    op.drop_index("ix_runtime_release_asset_id", table_name="runtime_release")
    op.drop_table("runtime_release")

    op.drop_column("runtime_executor", "update_state")
