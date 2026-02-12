from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.models  # noqa: F401  # Ensure SQLModel metadata registration.
from saki_api.models.enums import StorageType
from saki_api.models.storage.asset import Asset
from saki_api.models.storage.dataset import Dataset
from saki_api.models.storage.sample import Sample
from saki_api.models.access.user import User
from saki_api.repositories.storage.asset import AssetRepository


@pytest.fixture
async def asset_refs_env(tmp_path):
    db_path = tmp_path / "asset_refs.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        yield session_local
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_orphaned_assets_excludes_sample_and_avatar_references(asset_refs_env):
    session_local = asset_refs_env
    async with session_local() as session:
        user = User(email="user@example.com", hashed_password="hashed")
        session.add(user)
        await session.flush()
        dataset = Dataset(name="dataset-a", owner_id=user.id)
        session.add(dataset)
        await session.flush()

        sample_asset = Asset(
            hash="a" * 64,
            storage_type=StorageType.S3,
            path="assets/a/sample.png",
            bucket="bucket",
            original_filename="sample.png",
            extension=".png",
            mime_type="image/png",
            size=10,
        )
        avatar_asset = Asset(
            hash="b" * 64,
            storage_type=StorageType.S3,
            path="assets/b/avatar.png",
            bucket="bucket",
            original_filename="avatar.png",
            extension=".png",
            mime_type="image/png",
            size=10,
        )
        orphan_asset = Asset(
            hash="c" * 64,
            storage_type=StorageType.S3,
            path="assets/c/orphan.png",
            bucket="bucket",
            original_filename="orphan.png",
            extension=".png",
            mime_type="image/png",
            size=10,
        )
        session.add(sample_asset)
        session.add(avatar_asset)
        session.add(orphan_asset)
        await session.flush()

        user.avatar_url = f"asset://{avatar_asset.id}"
        session.add(user)

        sample = Sample(
            dataset_id=dataset.id,
            name="sample-1",
            primary_asset_id=sample_asset.id,
            asset_group={"main": str(sample_asset.id)},
        )
        session.add(sample)
        await session.commit()

        repo = AssetRepository(session)
        orphaned = await repo.get_orphaned_assets_older_than(
            older_than=datetime.now(UTC) + timedelta(days=1),
            limit=100,
        )
        orphaned_ids = {asset.id for asset in orphaned}

        assert orphan_asset.id in orphaned_ids
        assert sample_asset.id not in orphaned_ids
        assert avatar_asset.id not in orphaned_ids


@pytest.mark.anyio
async def test_is_referenced_considers_user_avatar(asset_refs_env):
    session_local = asset_refs_env
    async with session_local() as session:
        user = User(email="avatar-user@example.com", hashed_password="hashed")
        asset = Asset(
            hash="d" * 64,
            storage_type=StorageType.S3,
            path="assets/d/avatar.png",
            bucket="bucket",
            original_filename="avatar.png",
            extension=".png",
            mime_type="image/png",
            size=10,
        )
        session.add(user)
        session.add(asset)
        await session.flush()

        user.avatar_url = f"asset://{asset.id}"
        session.add(user)
        await session.commit()

        repo = AssetRepository(session)
        assert await repo.is_referenced(asset.id) is True

        user.avatar_url = None
        session.add(user)
        await session.commit()

        assert await repo.is_referenced(asset.id) is False
