from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.modules.shared.modeling  # noqa: F401
from saki_api.modules.access.domain.access.user import User
from saki_api.modules.access.domain.rbac import Role, RolePermission, RoleType, UserSystemRole
from saki_api.modules.access.service.presets import init_preset_roles


@pytest.fixture
async def preset_role_env(tmp_path):
    db_path = tmp_path / "preset_role_deprecation.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        yield session_local
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_init_preset_roles_deletes_unassigned_deprecated_system_role(preset_role_env):
    session_local = preset_role_env

    legacy_role_id = uuid.uuid4()
    async with session_local() as session:
        session.add(
            Role(
                id=legacy_role_id,
                name="legacy_dataset_operator",
                display_name="Legacy Dataset Operator",
                description="legacy",
                type=RoleType.RESOURCE,
                is_system=True,
                is_default=False,
                is_super_admin=False,
                is_admin=False,
                is_supremo=False,
                sort_order=999,
                color="gray",
            )
        )
        session.add(
            RolePermission(
                role_id=legacy_role_id,
                permission="dataset:read:assigned",
            )
        )
        await session.commit()

        await init_preset_roles(session)
        await session.commit()

        role_row = await session.exec(select(Role).where(Role.id == legacy_role_id))
        permission_rows = await session.exec(select(RolePermission).where(RolePermission.role_id == legacy_role_id))
        assert role_row.first() is None
        assert list(permission_rows.all()) == []


@pytest.mark.anyio
async def test_init_preset_roles_demotes_assigned_deprecated_system_role(preset_role_env):
    session_local = preset_role_env

    legacy_role_id = uuid.uuid4()
    user_id = uuid.uuid4()
    async with session_local() as session:
        session.add(
            Role(
                id=legacy_role_id,
                name="legacy_project_operator",
                display_name="Legacy Project Operator",
                description="legacy",
                type=RoleType.SYSTEM,
                is_system=True,
                is_default=True,
                is_super_admin=False,
                is_admin=True,
                is_supremo=True,
                sort_order=998,
                color="gray",
            )
        )
        session.add(
            User(
                id=user_id,
                email=f"legacy-user-{uuid.uuid4()}@example.com",
                hashed_password="hashed",
            )
        )
        session.add(
            UserSystemRole(
                user_id=user_id,
                role_id=legacy_role_id,
            )
        )
        await session.commit()

        await init_preset_roles(session)
        await session.commit()

        role_row = await session.exec(select(Role).where(Role.id == legacy_role_id))
        role = role_row.first()
        assert role is not None
        assert role.is_system is False
        assert role.is_default is False
        assert role.is_admin is False
        assert role.is_super_admin is False
        assert role.is_supremo is False
