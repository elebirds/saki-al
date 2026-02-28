"""al_snapshot_stage_refactor

Revision ID: b7f3a7d5c9c1
Revises: a00e4ff62324
Create Date: 2026-02-26 22:40:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "b7f3a7d5c9c1"
down_revision = "a00e4ff62324"
branch_labels = None
depends_on = None


loopstage_enum = postgresql.ENUM(
    "NEED_SNAPSHOT",
    "NEED_LABELS",
    "CAN_START",
    "RUNNING",
    "NEED_ROUND_LABELS",
    "CAN_CONFIRM",
    "COMPLETED",
    "STOPPED",
    "FAILED",
    name="loopstage",
)

snapshotupdatemode_enum = postgresql.ENUM(
    "INIT",
    "APPEND_ALL_TO_POOL",
    "APPEND_SPLIT",
    name="snapshotupdatemode",
)

snapshotvalpolicy_enum = postgresql.ENUM(
    "ANCHOR_ONLY",
    "EXPAND_WITH_BATCH_VAL",
    name="snapshotvalpolicy",
)

snapshotpartition_enum = postgresql.ENUM(
    "TRAIN_SEED",
    "TRAIN_POOL",
    "VAL_ANCHOR",
    "VAL_BATCH",
    "TEST_ANCHOR",
    "TEST_BATCH",
    name="snapshotpartition",
)

visibilitysource_enum = postgresql.ENUM(
    "SNAPSHOT_INIT",
    "SEED_INIT",
    "ROUND_REVEAL",
    "FORCE_REVEAL",
    name="visibilitysource",
)


def _create_enums() -> None:
    bind = op.get_bind()
    loopstage_enum.create(bind, checkfirst=True)
    snapshotupdatemode_enum.create(bind, checkfirst=True)
    snapshotvalpolicy_enum.create(bind, checkfirst=True)
    snapshotpartition_enum.create(bind, checkfirst=True)
    visibilitysource_enum.create(bind, checkfirst=True)


def _drop_enums() -> None:
    bind = op.get_bind()
    visibilitysource_enum.drop(bind, checkfirst=True)
    snapshotpartition_enum.drop(bind, checkfirst=True)
    snapshotvalpolicy_enum.drop(bind, checkfirst=True)
    snapshotupdatemode_enum.drop(bind, checkfirst=True)
    loopstage_enum.drop(bind, checkfirst=True)


def upgrade() -> None:
    _create_enums()

    op.add_column(
        "loop",
        sa.Column(
            "stage",
            loopstage_enum,
            nullable=False,
            server_default=sa.text("'NEED_SNAPSHOT'"),
        ),
    )
    op.add_column(
        "loop",
        sa.Column(
            "stage_meta",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(op.f("ix_loop_stage"), "loop", ["stage"], unique=False)

    op.execute("UPDATE loop SET stage = 'CAN_START' WHERE mode IN ('SIMULATION', 'MANUAL')")
    op.alter_column("loop", "stage", server_default=None)
    op.alter_column("loop", "stage_meta", server_default=None)

    op.create_table(
        "al_snapshot_version",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("loop_id", sa.Uuid(), nullable=False),
        sa.Column("version_index", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", sa.Uuid(), nullable=True),
        sa.Column("update_mode", snapshotupdatemode_enum, nullable=False),
        sa.Column("val_policy", snapshotvalpolicy_enum, nullable=False),
        sa.Column("seed", sa.String(length=128), nullable=False),
        sa.Column(
            "rule_json",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"]),
        sa.ForeignKeyConstraint(["loop_id"], ["loop.id"]),
        sa.ForeignKeyConstraint(["parent_version_id"], ["al_snapshot_version.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("loop_id", "version_index", name="uq_al_snapshot_version_loop_version"),
    )
    op.create_index(op.f("ix_al_snapshot_version_created_by"), "al_snapshot_version", ["created_by"], unique=False)
    op.create_index(op.f("ix_al_snapshot_version_loop_id"), "al_snapshot_version", ["loop_id"], unique=False)
    op.create_index(
        op.f("ix_al_snapshot_version_manifest_hash"),
        "al_snapshot_version",
        ["manifest_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_al_snapshot_version_parent_version_id"),
        "al_snapshot_version",
        ["parent_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_al_snapshot_version_update_mode"),
        "al_snapshot_version",
        ["update_mode"],
        unique=False,
    )
    op.create_index(
        op.f("ix_al_snapshot_version_val_policy"),
        "al_snapshot_version",
        ["val_policy"],
        unique=False,
    )
    op.create_index(
        op.f("ix_al_snapshot_version_version_index"),
        "al_snapshot_version",
        ["version_index"],
        unique=False,
    )

    op.create_table(
        "al_snapshot_sample",
        sa.Column("snapshot_version_id", sa.Uuid(), nullable=False),
        sa.Column("sample_id", sa.Uuid(), nullable=False),
        sa.Column("partition", snapshotpartition_enum, nullable=False),
        sa.Column("cohort_index", sa.Integer(), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["sample_id"], ["sample.id"]),
        sa.ForeignKeyConstraint(["snapshot_version_id"], ["al_snapshot_version.id"]),
        sa.PrimaryKeyConstraint("snapshot_version_id", "sample_id"),
    )
    op.create_index(op.f("ix_al_snapshot_sample_cohort_index"), "al_snapshot_sample", ["cohort_index"], unique=False)
    op.create_index(op.f("ix_al_snapshot_sample_locked"), "al_snapshot_sample", ["locked"], unique=False)
    op.create_index(op.f("ix_al_snapshot_sample_partition"), "al_snapshot_sample", ["partition"], unique=False)

    op.create_table(
        "al_loop_visibility",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("loop_id", sa.Uuid(), nullable=False),
        sa.Column("sample_id", sa.Uuid(), nullable=False),
        sa.Column("visible_in_train", sa.Boolean(), nullable=False),
        sa.Column("source", visibilitysource_enum, nullable=False),
        sa.Column("revealed_round_index", sa.Integer(), nullable=True),
        sa.Column("reveal_commit_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["loop_id"], ["loop.id"]),
        sa.ForeignKeyConstraint(["reveal_commit_id"], ["commit.id"]),
        sa.ForeignKeyConstraint(["sample_id"], ["sample.id"]),
        sa.PrimaryKeyConstraint("loop_id", "sample_id"),
    )
    op.create_index(
        op.f("ix_al_loop_visibility_reveal_commit_id"),
        "al_loop_visibility",
        ["reveal_commit_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_al_loop_visibility_revealed_round_index"),
        "al_loop_visibility",
        ["revealed_round_index"],
        unique=False,
    )
    op.create_index(op.f("ix_al_loop_visibility_source"), "al_loop_visibility", ["source"], unique=False)
    op.create_index(
        op.f("ix_al_loop_visibility_visible_in_train"),
        "al_loop_visibility",
        ["visible_in_train"],
        unique=False,
    )

    op.add_column("loop", sa.Column("active_snapshot_version_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_loop_active_snapshot_version_id"), "loop", ["active_snapshot_version_id"], unique=False)
    op.create_foreign_key(
        "fk_loop_active_snapshot_version_id_al_snapshot_version",
        "loop",
        "al_snapshot_version",
        ["active_snapshot_version_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_loop_active_snapshot_version_id_al_snapshot_version", "loop", type_="foreignkey")
    op.drop_index(op.f("ix_loop_active_snapshot_version_id"), table_name="loop")
    op.drop_column("loop", "active_snapshot_version_id")

    op.drop_index(op.f("ix_al_loop_visibility_visible_in_train"), table_name="al_loop_visibility")
    op.drop_index(op.f("ix_al_loop_visibility_source"), table_name="al_loop_visibility")
    op.drop_index(op.f("ix_al_loop_visibility_revealed_round_index"), table_name="al_loop_visibility")
    op.drop_index(op.f("ix_al_loop_visibility_reveal_commit_id"), table_name="al_loop_visibility")
    op.drop_table("al_loop_visibility")

    op.drop_index(op.f("ix_al_snapshot_sample_partition"), table_name="al_snapshot_sample")
    op.drop_index(op.f("ix_al_snapshot_sample_locked"), table_name="al_snapshot_sample")
    op.drop_index(op.f("ix_al_snapshot_sample_cohort_index"), table_name="al_snapshot_sample")
    op.drop_table("al_snapshot_sample")

    op.drop_index(op.f("ix_al_snapshot_version_version_index"), table_name="al_snapshot_version")
    op.drop_index(op.f("ix_al_snapshot_version_val_policy"), table_name="al_snapshot_version")
    op.drop_index(op.f("ix_al_snapshot_version_update_mode"), table_name="al_snapshot_version")
    op.drop_index(op.f("ix_al_snapshot_version_parent_version_id"), table_name="al_snapshot_version")
    op.drop_index(op.f("ix_al_snapshot_version_manifest_hash"), table_name="al_snapshot_version")
    op.drop_index(op.f("ix_al_snapshot_version_loop_id"), table_name="al_snapshot_version")
    op.drop_index(op.f("ix_al_snapshot_version_created_by"), table_name="al_snapshot_version")
    op.drop_table("al_snapshot_version")

    op.drop_index(op.f("ix_loop_stage"), table_name="loop")
    op.drop_column("loop", "stage_meta")
    op.drop_column("loop", "stage")

    _drop_enums()
