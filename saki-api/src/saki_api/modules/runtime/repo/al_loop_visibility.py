"""Repository for AL loop visibility."""

from __future__ import annotations

import uuid

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.modules.runtime.domain.al_loop_visibility import ALLoopVisibility
from saki_api.modules.shared.modeling.enums import VisibilitySource


class ALLoopVisibilityRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_loop(self, loop_id: uuid.UUID) -> list[ALLoopVisibility]:
        stmt = (
            select(ALLoopVisibility)
            .where(ALLoopVisibility.loop_id == loop_id)
            .order_by(ALLoopVisibility.sample_id.asc())
        )
        return list((await self.session.exec(stmt)).all())

    async def list_visible_sample_ids(self, loop_id: uuid.UUID) -> list[uuid.UUID]:
        stmt = (
            select(ALLoopVisibility.sample_id)
            .where(
                ALLoopVisibility.loop_id == loop_id,
                ALLoopVisibility.visible_in_train.is_(True),
            )
            .order_by(ALLoopVisibility.sample_id.asc())
        )
        return list((await self.session.exec(stmt)).all())

    async def upsert_rows(self, rows: list[dict]) -> None:
        if not rows:
            return
        stmt = pg_insert(ALLoopVisibility).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["loop_id", "sample_id"],
            set_={
                "visible_in_train": stmt.excluded.visible_in_train,
                "source": stmt.excluded.source,
                "revealed_round_index": stmt.excluded.revealed_round_index,
                "reveal_commit_id": stmt.excluded.reveal_commit_id,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        await self.session.exec(stmt)
        await self.session.flush()

    async def reset_loop(self, loop_id: uuid.UUID) -> None:
        await self.session.exec(delete(ALLoopVisibility).where(ALLoopVisibility.loop_id == loop_id))
        await self.session.flush()

    @staticmethod
    def build_row(
        *,
        loop_id: uuid.UUID,
        sample_id: uuid.UUID,
        visible_in_train: bool,
        source: VisibilitySource,
        revealed_round_index: int | None,
        reveal_commit_id: uuid.UUID | None,
    ) -> dict:
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        return {
            "loop_id": loop_id,
            "sample_id": sample_id,
            "visible_in_train": bool(visible_in_train),
            "source": source,
            "revealed_round_index": revealed_round_index,
            "reveal_commit_id": reveal_commit_id,
            "created_at": now,
            "updated_at": now,
        }
