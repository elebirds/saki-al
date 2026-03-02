"""model_publish_metadata_hardcut

Revision ID: a8b7c6d5e4f3
Revises: f7c1a2d9b4e6
Create Date: 2026-03-02 20:05:00.000000

"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "a8b7c6d5e4f3"
down_revision = "f7c1a2d9b4e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE model ADD COLUMN IF NOT EXISTS source_round_id UUID")
    op.execute("ALTER TABLE model ADD COLUMN IF NOT EXISTS source_step_id UUID")
    op.execute("ALTER TABLE model ADD COLUMN IF NOT EXISTS primary_artifact_name VARCHAR")
    op.execute("ALTER TABLE model ADD COLUMN IF NOT EXISTS publish_manifest JSONB")

    op.execute(
        """
        UPDATE model
        SET primary_artifact_name = COALESCE(
            NULLIF(regexp_replace(COALESCE(weights_path, ''), '^.*/', ''), ''),
            'best.pt'
        )
        WHERE primary_artifact_name IS NULL OR primary_artifact_name = '';
        """
    )
    op.execute("UPDATE model SET publish_manifest = '{}'::jsonb WHERE publish_manifest IS NULL")

    op.execute("ALTER TABLE model ALTER COLUMN primary_artifact_name SET NOT NULL")
    op.execute("ALTER TABLE model ALTER COLUMN publish_manifest SET NOT NULL")

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_model_source_round_id'
            ) THEN
                ALTER TABLE model
                ADD CONSTRAINT fk_model_source_round_id
                FOREIGN KEY (source_round_id) REFERENCES round(id);
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_model_source_step_id'
            ) THEN
                ALTER TABLE model
                ADD CONSTRAINT fk_model_source_step_id
                FOREIGN KEY (source_step_id) REFERENCES step(id);
            END IF;
        END $$;
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS ix_model_source_round_id ON model(source_round_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_model_source_step_id ON model(source_step_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_model_publish_key "
        "ON model(project_id, source_round_id, primary_artifact_name, version_tag) "
        "WHERE source_round_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_model_publish_key")
    op.execute("DROP INDEX IF EXISTS ix_model_source_step_id")
    op.execute("DROP INDEX IF EXISTS ix_model_source_round_id")
    op.execute("ALTER TABLE model DROP CONSTRAINT IF EXISTS fk_model_source_step_id")
    op.execute("ALTER TABLE model DROP CONSTRAINT IF EXISTS fk_model_source_round_id")
    op.execute("ALTER TABLE model DROP COLUMN IF EXISTS publish_manifest")
    op.execute("ALTER TABLE model DROP COLUMN IF EXISTS primary_artifact_name")
    op.execute("ALTER TABLE model DROP COLUMN IF EXISTS source_step_id")
    op.execute("ALTER TABLE model DROP COLUMN IF EXISTS source_round_id")
