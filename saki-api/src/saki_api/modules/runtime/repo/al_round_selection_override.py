"""Repository for AL round selection overrides."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.modules.runtime.domain.al_round_selection_override import ALRoundSelectionOverride
from saki_api.modules.shared.modeling.enums import RoundSelectionOverrideOp


class ALRoundSelectionOverrideRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_round(self, round_id: uuid.UUID) -> list[ALRoundSelectionOverride]:
        stmt = (
            select(ALRoundSelectionOverride)
            .where(ALRoundSelectionOverride.round_id == round_id)
            .order_by(ALRoundSelectionOverride.created_at.asc(), ALRoundSelectionOverride.sample_id.asc())
        )
        return list((await self.session.exec(stmt)).all())

    async def replace_round_overrides(
        self,
        *,
        round_id: uuid.UUID,
        include_ids: list[uuid.UUID],
        exclude_ids: list[uuid.UUID],
        created_by: uuid.UUID | None,
        reason: str | None = None,
    ) -> None:
        keep_ids = set(include_ids) | set(exclude_ids)
        if keep_ids:
            await self.session.exec(
                delete(ALRoundSelectionOverride).where(
                    ALRoundSelectionOverride.round_id == round_id,
                    ALRoundSelectionOverride.sample_id.not_in(list(keep_ids)),
                )
            )
        else:
            await self.session.exec(
                delete(ALRoundSelectionOverride).where(ALRoundSelectionOverride.round_id == round_id)
            )
            await self.session.flush()
            return

        now = datetime.now(UTC)
        rows: list[dict] = []
        rows.extend(
            {
                "round_id": round_id,
                "sample_id": sample_id,
                "op": RoundSelectionOverrideOp.INCLUDE,
                "created_by": created_by,
                "reason": reason,
                "created_at": now,
                "updated_at": now,
            }
            for sample_id in include_ids
        )
        rows.extend(
            {
                "round_id": round_id,
                "sample_id": sample_id,
                "op": RoundSelectionOverrideOp.EXCLUDE,
                "created_by": created_by,
                "reason": reason,
                "created_at": now,
                "updated_at": now,
            }
            for sample_id in exclude_ids
        )
        if rows:
            stmt = pg_insert(ALRoundSelectionOverride).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["round_id", "sample_id"],
                set_={
                    "op": stmt.excluded.op,
                    "created_by": stmt.excluded.created_by,
                    "reason": stmt.excluded.reason,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            await self.session.exec(stmt)
        await self.session.flush()

    async def reset_round(self, round_id: uuid.UUID) -> None:
        await self.session.exec(delete(ALRoundSelectionOverride).where(ALRoundSelectionOverride.round_id == round_id))
        await self.session.flush()
