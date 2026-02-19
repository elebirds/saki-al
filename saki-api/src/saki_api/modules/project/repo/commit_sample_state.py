"""
CommitSampleState repository.
"""

import uuid

from sqlalchemy import delete, insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.modules.project.domain.commit_sample_state import CommitSampleState
from saki_api.modules.shared.modeling.enums import CommitSampleReviewState


class CommitSampleStateRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def copy_commit_state(
            self,
            *,
            source_commit_id: uuid.UUID,
            target_commit_id: uuid.UUID,
            project_id: uuid.UUID,
    ) -> None:
        rows = await self.session.exec(
            select(CommitSampleState).where(CommitSampleState.commit_id == source_commit_id)
        )
        for row in rows.all():
            self.session.add(
                CommitSampleState(
                    commit_id=target_commit_id,
                    sample_id=row.sample_id,
                    project_id=project_id,
                    state=row.state,
                )
            )
        await self.session.flush()

    async def delete_commit_sample_state(
            self,
            *,
            commit_id: uuid.UUID,
            sample_id: uuid.UUID,
    ) -> int:
        return await self.delete_commit_sample_states(
            commit_id=commit_id,
            sample_ids=[sample_id],
        )

    async def set_commit_sample_state(
            self,
            *,
            commit_id: uuid.UUID,
            sample_id: uuid.UUID,
            project_id: uuid.UUID,
            state: CommitSampleReviewState,
    ) -> None:
        await self.set_commit_sample_states(
            commit_id=commit_id,
            project_id=project_id,
            mappings=[(sample_id, state)],
        )

    async def delete_commit_sample_states(
            self,
            *,
            commit_id: uuid.UUID,
            sample_ids: list[uuid.UUID],
    ) -> int:
        unique_sample_ids = list(set(sample_ids))
        if not unique_sample_ids:
            return 0
        stmt = delete(CommitSampleState).where(
            CommitSampleState.commit_id == commit_id,
            CommitSampleState.sample_id.in_(unique_sample_ids),
        )
        result = await self.session.exec(stmt)
        await self.session.flush()
        return int(result.rowcount or 0)

    async def set_commit_sample_states(
            self,
            *,
            commit_id: uuid.UUID,
            project_id: uuid.UUID,
            mappings: list[tuple[uuid.UUID, CommitSampleReviewState]],
    ) -> None:
        if not mappings:
            return
        deduped_mappings = list(dict.fromkeys(mappings))
        rows = [
            {
                "commit_id": commit_id,
                "sample_id": sample_id,
                "project_id": project_id,
                "state": state,
            }
            for sample_id, state in deduped_mappings
        ]
        await self.session.execute(insert(CommitSampleState), rows)
        await self.session.flush()
