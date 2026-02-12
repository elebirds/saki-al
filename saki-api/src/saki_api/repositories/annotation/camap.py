"""
CAMap Repository - Data access layer for CommitAnnotationMap operations.
"""

import uuid
from typing import List, Tuple, Dict

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.annotation.camap import CommitAnnotationMap


class CAMapRepository:
    """
    Repository for CommitAnnotationMap data access.

    This is the performance engine for L2 version control - it determines
    which annotations are visible at any given commit.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_annotations_for_commit(
            self,
            commit_id: uuid.UUID,
    ) -> Dict[uuid.UUID, List[uuid.UUID]]:
        """
        Get all annotation IDs for a commit grouped by sample_id.

        Args:
            commit_id: Commit ID

        Returns:
            Dictionary mapping sample_id -> list of annotation_ids
        """
        statement = select(
            CommitAnnotationMap.sample_id,
            CommitAnnotationMap.annotation_id,
        ).where(
            CommitAnnotationMap.commit_id == commit_id,
        )
        result = await self.session.exec(statement)
        mappings = result.all()

        # Group by sample_id
        sample_annotations: Dict[uuid.UUID, List[uuid.UUID]] = {}
        for sample_id, annotation_id in mappings:
            if sample_id not in sample_annotations:
                sample_annotations[sample_id] = []
            sample_annotations[sample_id].append(annotation_id)

        return sample_annotations

    async def get_sample_annotations(
            self,
            commit_id: uuid.UUID,
            sample_id: uuid.UUID,
    ) -> List[uuid.UUID]:
        """
        Get all annotation IDs for a specific sample at a commit.

        Args:
            commit_id: Commit ID
            sample_id: Sample ID

        Returns:
            List of annotation IDs
        """
        statement = select(CommitAnnotationMap.annotation_id).where(
            CommitAnnotationMap.commit_id == commit_id,
            CommitAnnotationMap.sample_id == sample_id,
        )
        result = await self.session.exec(statement)
        return list(result.all())

    async def set_commit_state(
            self,
            commit_id: uuid.UUID,
            mappings: List[Tuple[uuid.UUID, uuid.UUID]],
            project_id: uuid.UUID,
    ) -> None:
        """
        Batch insert CAMap entries for a commit.

        Args:
            commit_id: Commit ID
            mappings: List of (sample_id, annotation_id) tuples
            project_id: Project ID (for all entries)
        """
        for sample_id, annotation_id in mappings:
            entry = CommitAnnotationMap(
                commit_id=commit_id,
                sample_id=sample_id,
                annotation_id=annotation_id,
                project_id=project_id,
            )
            self.session.add(entry)

        await self.session.flush()

    async def delete_commit_state(self, commit_id: uuid.UUID) -> int:
        """
        Delete all CAMap entries for a commit.

        Args:
            commit_id: Commit ID

        Returns:
            Number of entries deleted
        """
        statement = select(CommitAnnotationMap).where(
            CommitAnnotationMap.commit_id == commit_id,
        )
        result = await self.session.exec(statement)
        entries = result.all()

        count = len(entries)
        for entry in entries:
            await self.session.delete(entry)

        await self.session.flush()
        return count

    async def delete_commit_sample_state(
            self,
            commit_id: uuid.UUID,
            sample_id: uuid.UUID,
    ) -> int:
        """
        Delete CAMap entries for a specific sample at a commit.

        Args:
            commit_id: Commit ID
            sample_id: Sample ID

        Returns:
            Number of entries deleted
        """
        statement = select(CommitAnnotationMap).where(
            CommitAnnotationMap.commit_id == commit_id,
            CommitAnnotationMap.sample_id == sample_id,
        )
        result = await self.session.exec(statement)
        entries = result.all()

        count = len(entries)
        for entry in entries:
            await self.session.delete(entry)

        await self.session.flush()
        return count

    async def count_annotations_at_commit(self, commit_id: uuid.UUID) -> int:
        """
        Count total annotations at a commit.

        Args:
            commit_id: Commit ID

        Returns:
            Number of annotations
        """
        statement = select(func.count()).select_from(
            select(CommitAnnotationMap).where(
                CommitAnnotationMap.commit_id == commit_id,
            ).subquery()
        )
        result = await self.session.exec(statement)
        return result.one() or 0

    async def count_samples_at_commit(self, commit_id: uuid.UUID) -> int:
        """
        Count unique samples with annotations at a commit.

        Args:
            commit_id: Commit ID

        Returns:
            Number of samples
        """
        statement = select(func.count(func.distinct(CommitAnnotationMap.sample_id))).where(
            CommitAnnotationMap.commit_id == commit_id,
        )
        result = await self.session.exec(statement)
        return result.one() or 0

    async def get_commit_stats(self, commit_id: uuid.UUID) -> Dict:
        """
        Get statistics for a commit.

        Args:
            commit_id: Commit ID

        Returns:
            Dictionary with annotation_count and sample_count
        """
        statement = select(
            func.count(func.distinct(CommitAnnotationMap.sample_id)),
            func.count(CommitAnnotationMap.annotation_id),
        ).where(
            CommitAnnotationMap.commit_id == commit_id,
        )
        result = await self.session.exec(statement)
        row = result.first()

        if not row:
            return {"sample_count": 0, "annotation_count": 0}

        return {
            "sample_count": row[0],
            "annotation_count": row[1],
        }
