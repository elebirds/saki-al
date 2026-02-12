"""Storage module cross-context contracts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.modules.storage.service.asset import AssetService


@dataclass(slots=True)
class AssetGcItemDTO:
    id: uuid.UUID
    path: str


class AssetGcContract(Protocol):
    async def list_orphaned_assets(
            self,
            *,
            older_than: datetime,
            limit: int = 1000,
    ) -> list[AssetGcItemDTO]:
        """List orphaned assets that are eligible for GC."""

    async def delete_asset_record(self, asset_id: uuid.UUID) -> bool:
        """Delete asset record from DB (object deletion handled by caller)."""


class AssetGcGateway(AssetGcContract):
    """Cross-module facade for storage orphan-asset cleanup."""

    def __init__(self, session: AsyncSession) -> None:
        self._asset_service = AssetService(session=session)

    async def list_orphaned_assets(
            self,
            *,
            older_than: datetime,
            limit: int = 1000,
    ) -> list[AssetGcItemDTO]:
        assets = await self._asset_service.list_orphaned_assets_older_than(
            older_than=older_than,
            limit=limit,
        )
        return [AssetGcItemDTO(id=asset.id, path=asset.path) for asset in assets]

    async def delete_asset_record(self, asset_id: uuid.UUID) -> bool:
        return await self._asset_service.delete_asset_record(asset_id)
