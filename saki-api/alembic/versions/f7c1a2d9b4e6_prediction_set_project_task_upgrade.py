"""prediction_set_project_task_upgrade

Revision ID: f7c1a2d9b4e6
Revises: e5a1c9f2b4d3
Create Date: 2026-03-02 17:10:00.000000

"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "f7c1a2d9b4e6"
down_revision = ("1c3a6d7e9f20", "e5a1c9f2b4d3")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE prediction_set ADD COLUMN IF NOT EXISTS project_id UUID")
    op.execute(
        """
        UPDATE prediction_set AS ps
        SET project_id = l.project_id
        FROM loop AS l
        WHERE ps.project_id IS NULL
          AND ps.loop_id IS NOT NULL
          AND l.id = ps.loop_id
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM prediction_set WHERE project_id IS NULL) THEN
                RAISE EXCEPTION 'prediction_set.project_id backfill failed';
            END IF;
        END $$;
        """
    )
    op.execute("ALTER TABLE prediction_set ALTER COLUMN project_id SET NOT NULL")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_prediction_set_project_id'
            ) THEN
                ALTER TABLE prediction_set
                ADD CONSTRAINT fk_prediction_set_project_id
                FOREIGN KEY (project_id) REFERENCES project(id);
            END IF;
        END $$;
        """
    )

    op.execute("ALTER TABLE prediction_set ALTER COLUMN loop_id DROP NOT NULL")

    op.execute("ALTER TABLE prediction_set ADD COLUMN IF NOT EXISTS plugin_id VARCHAR(255)")
    op.execute(
        """
        UPDATE prediction_set AS ps
        SET plugin_id = COALESCE(r.plugin_id, '')
        FROM round AS r
        WHERE ps.source_round_id = r.id
          AND (ps.plugin_id IS NULL OR ps.plugin_id = '');
        """
    )
    op.execute(
        """
        UPDATE prediction_set AS ps
        SET plugin_id = COALESCE(l.model_arch, '')
        FROM loop AS l
        WHERE ps.loop_id = l.id
          AND (ps.plugin_id IS NULL OR ps.plugin_id = '');
        """
    )
    op.execute("UPDATE prediction_set SET plugin_id = 'unknown' WHERE plugin_id IS NULL OR plugin_id = ''")
    op.execute("ALTER TABLE prediction_set ALTER COLUMN plugin_id SET NOT NULL")

    op.execute("ALTER TABLE prediction_set ADD COLUMN IF NOT EXISTS last_error TEXT")

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_prediction_set_project_id_created_at_desc "
        "ON prediction_set(project_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_prediction_set_project_id_status "
        "ON prediction_set(project_id, status)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_prediction_set_plugin_id ON prediction_set(plugin_id)")


def downgrade() -> None:
    # Keep downgrade as no-op to avoid lossy column rollback in production data.
    pass
