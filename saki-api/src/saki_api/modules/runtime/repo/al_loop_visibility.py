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
    _POSTGRES_MAX_BIND_PARAMS = 65535

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
        batch_size = self._resolve_upsert_batch_size(rows)
        for start in range(0, len(rows), batch_size):
            batch = rows[start:start + batch_size]
            stmt = pg_insert(ALLoopVisibility).values(batch)
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

    def _resolve_upsert_batch_size(self, rows: list[dict]) -> int:
        max_bind_params = self._resolve_bind_param_limit()
        if max_bind_params is None:
            return len(rows)
        max_fields_per_row = max(1, max(len(row) for row in rows))
        return max(1, max_bind_params // max_fields_per_row)

    def _resolve_bind_param_limit(self) -> int | None:
        get_bind = getattr(self.session, "get_bind", None)
        if not callable(get_bind):
            return self._POSTGRES_MAX_BIND_PARAMS
        try:
            bind = get_bind()
        except Exception:
            return self._POSTGRES_MAX_BIND_PARAMS
        dialect = str(getattr(getattr(bind, "dialect", None), "name", "")).strip().lower()
        if dialect and dialect != "postgresql":
            return None
        return self._POSTGRES_MAX_BIND_PARAMS

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
