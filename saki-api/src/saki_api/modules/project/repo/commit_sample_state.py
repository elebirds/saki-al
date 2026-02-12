"""
CommitSampleState repository.
"""

import uuid

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
        rows = await self.session.exec(
            select(CommitSampleState).where(
                CommitSampleState.commit_id == commit_id,
                CommitSampleState.sample_id == sample_id,
            )
        )
        items = list(rows.all())
        for item in items:
            await self.session.delete(item)
        await self.session.flush()
        return len(items)

    async def set_commit_sample_state(
            self,
            *,
            commit_id: uuid.UUID,
            sample_id: uuid.UUID,
            project_id: uuid.UUID,
            state: CommitSampleReviewState,
    ) -> None:
        self.session.add(
            CommitSampleState(
                commit_id=commit_id,
                sample_id=sample_id,
                project_id=project_id,
                state=state,
            )
        )
        await self.session.flush()

