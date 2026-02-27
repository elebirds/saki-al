"""Repository for AL snapshot samples."""

from __future__ import annotations

import uuid

from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.modules.runtime.domain.al_snapshot_sample import ALSnapshotSample
from saki_api.modules.shared.modeling.enums import SnapshotPartition


class ALSnapshotSampleRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_snapshot(self, snapshot_version_id: uuid.UUID) -> list[ALSnapshotSample]:
        stmt = (
            select(ALSnapshotSample)
            .where(ALSnapshotSample.snapshot_version_id == snapshot_version_id)
            .order_by(ALSnapshotSample.sample_id.asc())
        )
        return list((await self.session.exec(stmt)).all())

    async def list_sample_ids_by_snapshot(self, snapshot_version_id: uuid.UUID) -> list[uuid.UUID]:
        stmt = (
            select(ALSnapshotSample.sample_id)
            .where(ALSnapshotSample.snapshot_version_id == snapshot_version_id)
            .order_by(ALSnapshotSample.sample_id.asc())
        )
        return list((await self.session.exec(stmt)).all())

    async def list_sample_ids_by_partitions(
        self,
        snapshot_version_id: uuid.UUID,
        partitions: list[SnapshotPartition],
    ) -> list[uuid.UUID]:
        if not partitions:
            return []
        stmt = (
            select(ALSnapshotSample.sample_id)
            .where(
                ALSnapshotSample.snapshot_version_id == snapshot_version_id,
                ALSnapshotSample.partition.in_(partitions),
            )
            .order_by(ALSnapshotSample.sample_id.asc())
        )
        return list((await self.session.exec(stmt)).all())

    async def replace_snapshot_rows(
        self,
        *,
        snapshot_version_id: uuid.UUID,
        rows: list[dict],
    ) -> None:
        await self.session.exec(
            delete(ALSnapshotSample).where(ALSnapshotSample.snapshot_version_id == snapshot_version_id)
        )
        if not rows:
            await self.session.flush()
            return
        self.session.add_all(
            [
                ALSnapshotSample(
                    snapshot_version_id=snapshot_version_id,
                    sample_id=row["sample_id"],
                    partition=row["partition"],
                    cohort_index=int(row.get("cohort_index", 0)),
                    locked=bool(row.get("locked", False)),
                )
                for row in rows
            ]
        )
        await self.session.flush()
