"""runtime_unified_semantics_hardcut_v3

Revision ID: c3d5e7f9a1b2
Revises: bb2d8f1a4c7e
Create Date: 2026-03-01 21:10:00.000000

"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "c3d5e7f9a1b2"
down_revision = "bb2d8f1a4c7e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Enum hard-cut: loopphase
    op.execute(
        """
        CREATE TYPE loopphase_v3 AS ENUM (
            'AL_BOOTSTRAP',
            'AL_TRAIN',
            'AL_EVAL',
            'AL_SCORE',
            'AL_SELECT',
            'AL_WAIT_USER',
            'AL_FINALIZE',
            'SIM_BOOTSTRAP',
            'SIM_TRAIN',
            'SIM_EVAL',
            'SIM_SCORE',
            'SIM_SELECT',
            'SIM_WAIT_USER',
            'SIM_FINALIZE',
            'MANUAL_BOOTSTRAP',
            'MANUAL_TRAIN',
            'MANUAL_EVAL',
            'MANUAL_FINALIZE'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE loop
        ALTER COLUMN phase TYPE loopphase_v3
        USING (
            CASE phase::text
                WHEN 'SIM_ACTIVATE' THEN 'SIM_SELECT'
                WHEN 'MANUAL_EXPORT' THEN 'MANUAL_EVAL'
                ELSE phase::text
            END
        )::loopphase_v3
        """
    )
    op.execute("DROP TYPE loopphase")
    op.execute("ALTER TYPE loopphase_v3 RENAME TO loopphase")

    # 2) Enum hard-cut: steptype
    op.execute(
        """
        CREATE TYPE steptype_v3 AS ENUM (
            'TRAIN',
            'EVAL',
            'SCORE',
            'SELECT',
            'PREDICT',
            'CUSTOM'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE step
        ALTER COLUMN step_type TYPE steptype_v3
        USING (
            CASE step_type::text
                WHEN 'ACTIVATE_SAMPLES' THEN 'SELECT'
                WHEN 'ADVANCE_BRANCH' THEN 'SELECT'
                WHEN 'EXPORT' THEN 'CUSTOM'
                WHEN 'UPLOAD_ARTIFACT' THEN 'CUSTOM'
                ELSE step_type::text
            END
        )::steptype_v3
        """
    )
    op.execute("DROP TYPE steptype")
    op.execute("ALTER TYPE steptype_v3 RENAME TO steptype")

    # 3) Snapshot/visibility tables rename (AL -> generic)
    op.execute("ALTER TABLE IF EXISTS al_snapshot_version RENAME TO loop_snapshot_version")
    op.execute("ALTER TABLE IF EXISTS al_snapshot_sample RENAME TO loop_snapshot_sample")
    op.execute("ALTER TABLE IF EXISTS al_loop_visibility RENAME TO loop_sample_state")

    # 4) Round selection override table rename (AL -> generic)
    op.execute("ALTER TABLE IF EXISTS al_round_selection_override RENAME TO round_selection_override")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_al_round_selection_override_round_sample'
            ) THEN
                ALTER TABLE round_selection_override
                RENAME CONSTRAINT uq_al_round_selection_override_round_sample
                TO uq_round_selection_override_round_sample;
            END IF;
        END $$;
        """
    )
    op.execute("ALTER INDEX IF EXISTS ix_al_round_selection_override_round_id RENAME TO ix_round_selection_override_round_id")
    op.execute("ALTER INDEX IF EXISTS ix_al_round_selection_override_sample_id RENAME TO ix_round_selection_override_sample_id")
    op.execute("ALTER INDEX IF EXISTS ix_al_round_selection_override_op RENAME TO ix_round_selection_override_op")
    op.execute("ALTER INDEX IF EXISTS ix_al_round_selection_override_created_by RENAME TO ix_round_selection_override_created_by")

    # 5) Prediction set + item tables
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS prediction_set (
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            id UUID NOT NULL PRIMARY KEY,
            loop_id UUID NOT NULL REFERENCES loop(id),
            source_round_id UUID NULL REFERENCES round(id),
            source_step_id UUID NULL REFERENCES step(id),
            model_id UUID NULL REFERENCES model(id),
            base_commit_id UUID NULL REFERENCES commit(id),
            scope_type VARCHAR(64) NOT NULL DEFAULT 'snapshot_scope',
            scope_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            total_items INTEGER NOT NULL DEFAULT 0,
            params JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_by UUID NULL REFERENCES "user"(id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_prediction_set_loop_id ON prediction_set(loop_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_prediction_set_source_round_id ON prediction_set(source_round_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_prediction_set_source_step_id ON prediction_set(source_step_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_prediction_set_model_id ON prediction_set(model_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_prediction_set_base_commit_id ON prediction_set(base_commit_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_prediction_set_scope_type ON prediction_set(scope_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_prediction_set_status ON prediction_set(status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_prediction_set_created_by ON prediction_set(created_by)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS prediction_item (
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            prediction_set_id UUID NOT NULL REFERENCES prediction_set(id) ON DELETE CASCADE,
            sample_id UUID NOT NULL REFERENCES sample(id),
            rank INTEGER NOT NULL DEFAULT 0,
            score DOUBLE PRECISION NOT NULL DEFAULT 0,
            label_id UUID NULL REFERENCES label(id),
            geometry JSONB NOT NULL DEFAULT '{}'::jsonb,
            attrs JSONB NOT NULL DEFAULT '{}'::jsonb,
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
            meta JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (prediction_set_id, sample_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_prediction_item_rank ON prediction_item(rank)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_prediction_item_label_id ON prediction_item(label_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_prediction_item_sample_id ON prediction_item(sample_id)")


def downgrade() -> None:
    # 1) Drop prediction resources.
    op.execute("DROP TABLE IF EXISTS prediction_item")
    op.execute("DROP TABLE IF EXISTS prediction_set")

    # 2) Rename generic tables back to AL-prefixed names.
    op.execute("ALTER TABLE IF EXISTS round_selection_override RENAME TO al_round_selection_override")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_round_selection_override_round_sample'
            ) THEN
                ALTER TABLE al_round_selection_override
                RENAME CONSTRAINT uq_round_selection_override_round_sample
                TO uq_al_round_selection_override_round_sample;
            END IF;
        END $$;
        """
    )
    op.execute("ALTER INDEX IF EXISTS ix_round_selection_override_round_id RENAME TO ix_al_round_selection_override_round_id")
    op.execute("ALTER INDEX IF EXISTS ix_round_selection_override_sample_id RENAME TO ix_al_round_selection_override_sample_id")
    op.execute("ALTER INDEX IF EXISTS ix_round_selection_override_op RENAME TO ix_al_round_selection_override_op")
    op.execute("ALTER INDEX IF EXISTS ix_round_selection_override_created_by RENAME TO ix_al_round_selection_override_created_by")

    op.execute("ALTER TABLE IF EXISTS loop_sample_state RENAME TO al_loop_visibility")
    op.execute("ALTER TABLE IF EXISTS loop_snapshot_sample RENAME TO al_snapshot_sample")
    op.execute("ALTER TABLE IF EXISTS loop_snapshot_version RENAME TO al_snapshot_version")

    # 3) Restore legacy steptype enum values.
    op.execute(
        """
        CREATE TYPE steptype_legacy AS ENUM (
            'TRAIN',
            'SCORE',
            'SELECT',
            'ACTIVATE_SAMPLES',
            'ADVANCE_BRANCH',
            'EVAL',
            'EXPORT',
            'UPLOAD_ARTIFACT',
            'CUSTOM'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE step
        ALTER COLUMN step_type TYPE steptype_legacy
        USING (
            CASE step_type::text
                WHEN 'PREDICT' THEN 'SCORE'
                ELSE step_type::text
            END
        )::steptype_legacy
        """
    )
    op.execute("DROP TYPE steptype")
    op.execute("ALTER TYPE steptype_legacy RENAME TO steptype")

    # 4) Restore legacy loopphase enum values.
    op.execute(
        """
        CREATE TYPE loopphase_legacy AS ENUM (
            'AL_BOOTSTRAP',
            'AL_TRAIN',
            'AL_SCORE',
            'AL_SELECT',
            'AL_WAIT_USER',
            'AL_EVAL',
            'AL_FINALIZE',
            'SIM_BOOTSTRAP',
            'SIM_TRAIN',
            'SIM_SCORE',
            'SIM_SELECT',
            'SIM_ACTIVATE',
            'SIM_EVAL',
            'SIM_FINALIZE',
            'MANUAL_BOOTSTRAP',
            'MANUAL_TRAIN',
            'MANUAL_EVAL',
            'MANUAL_EXPORT',
            'MANUAL_FINALIZE'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE loop
        ALTER COLUMN phase TYPE loopphase_legacy
        USING (
            CASE phase::text
                WHEN 'SIM_WAIT_USER' THEN 'SIM_SELECT'
                ELSE phase::text
            END
        )::loopphase_legacy
        """
    )
    op.execute("DROP TYPE loopphase")
    op.execute("ALTER TYPE loopphase_legacy RENAME TO loopphase")
