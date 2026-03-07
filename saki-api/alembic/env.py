from __future__ import annotations

import asyncio
import hashlib
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from alembic.operations import ops
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.schema import ForeignKeyConstraint
from sqlmodel import SQLModel

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

from saki_api.core.config import settings  # noqa: E402
import saki_api.infra.db.models  # noqa: F401,E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

target_metadata = SQLModel.metadata


_CYCLE_TABLES = {"loop", "loop_snapshot_version", "round", "model"}


def _fk_name(table_name: str, constraint: ForeignKeyConstraint) -> str:
    if constraint.name:
        return constraint.name
    local_cols = "_".join(constraint.column_keys)
    referred_table = list(constraint.elements)[0].column.table.name
    base = f"fk_{table_name}_{local_cols}_{referred_table}"
    if len(base) > 60:
        digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
        base = f"fk_{table_name}_{digest}"
    return base


def _process_revision_directives(context, revision, directives) -> None:
    if not directives:
        return
    script = directives[0]
    if not hasattr(script, "upgrade_ops"):
        return

    upgrade_ops = script.upgrade_ops
    downgrade_ops = script.downgrade_ops

    new_upgrade_ops = []
    add_fk_ops = []
    drop_fk_ops = []

    for op in upgrade_ops.ops:
        if isinstance(op, ops.CreateTableOp) and op.table_name in _CYCLE_TABLES:
            fk_constraints = [
                c for c in op.columns if isinstance(c, ForeignKeyConstraint)
            ]
            if fk_constraints:
                fk_ids = {id(c) for c in fk_constraints}
                op.columns = [
                    c for c in op.columns if id(c) not in fk_ids
                ]
                for col in op.columns:
                    if hasattr(col, "foreign_keys") and col.foreign_keys:
                        col.foreign_keys.clear()
                new_upgrade_ops.append(op)
                for fk in fk_constraints:
                    fk_op = ops.CreateForeignKeyOp.from_constraint(fk)
                    if fk_op.constraint_name is None:
                        fk_op.constraint_name = _fk_name(op.table_name, fk)
                    add_fk_ops.append(fk_op)
                    drop_fk_ops.append(
                        ops.DropConstraintOp(
                            fk_op.constraint_name,
                            op.table_name,
                            type_="foreignkey",
                        )
                    )
                continue
        new_upgrade_ops.append(op)

    if add_fk_ops:
        upgrade_ops.ops = new_upgrade_ops + add_fk_ops
        downgrade_ops.ops = drop_fk_ops + downgrade_ops.ops


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
        dialect_opts={"paramstyle": "named"},
        process_revision_directives=_process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        process_revision_directives=_process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
