"""
CAMap Service - Business logic for CommitAnnotationMap operations.
"""

import uuid
from typing import List, Dict

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.transaction import transactional
from saki_api.modules.annotation.repo.annotation import AnnotationRepository
from saki_api.modules.annotation.repo.camap import CAMapRepository


class CAMapService:
    """
    Service for managing CommitAnnotationMap (L2 Performance Engine).

    CAMap is the index that determines which annotations are visible
    at any given commit. This service provides high-performance queries
    for commit-state lookups.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.camap_repo = CAMapRepository(session)
        self.annotation_repo = AnnotationRepository(session)

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
        return await self.camap_repo.get_annotations_for_commit(commit_id)

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
        return await self.camap_repo.get_sample_annotations(commit_id, sample_id)

    async def get_sample_annotations_full(
            self,
            commit_id: uuid.UUID,
            sample_id: uuid.UUID,
    ) -> List:
        """
        Get full annotation objects for a sample at a commit.

        Args:
            commit_id: Commit ID
            sample_id: Sample ID

        Returns:
            List of Annotation objects
        """
        annotation_ids = await self.camap_repo.get_sample_annotations(
            commit_id, sample_id
        )

        annotations = []
        for ann_id in annotation_ids:
            ann = await self.annotation_repo.get_by_id(ann_id)
            if ann:
                annotations.append(ann)

        return annotations

    @transactional
    async def create_commit_state(
            self,
            commit_id: uuid.UUID,
            annotations: List,
            project_id: uuid.UUID,
    ) -> None:
        """
        Create CAMap entries for a new commit.

        Args:
            commit_id: Commit ID
            annotations: List of Annotation objects to map
            project_id: Project ID
        """
        # Build (sample_id, annotation_id) mappings
        mappings = [(a.sample_id, a.id) for a in annotations]

        await self.camap_repo.set_commit_state(
            commit_id=commit_id,
            mappings=mappings,
            project_id=project_id,
        )

    @transactional
    async def copy_commit_state(
            self,
            source_commit_id: uuid.UUID,
            target_commit_id: uuid.UUID,
            project_id: uuid.UUID,
    ) -> None:
        """
        Copy CAMap entries from one commit to another.

        Useful for creating branches or cherry-picking commits.

        Args:
            source_commit_id: Source commit ID
            target_commit_id: Target commit ID
            project_id: Project ID
        """
        # Get source state
        source_state = await self.camap_repo.get_annotations_for_commit(
            source_commit_id
        )

        # Flatten to list of (sample_id, annotation_id) tuples
        mappings = []
        for sample_id, annotation_ids in source_state.items():
            for annotation_id in annotation_ids:
                mappings.append((sample_id, annotation_id))

        # Create target state
        await self.camap_repo.set_commit_state(
            commit_id=target_commit_id,
            mappings=mappings,
            project_id=project_id,
        )

    async def get_commit_stats(self, commit_id: uuid.UUID) -> Dict:
        """
        Get statistics for a commit.

        Args:
            commit_id: Commit ID

        Returns:
            Dictionary with sample_count and annotation_count
        """
        return await self.camap_repo.get_commit_stats(commit_id)

    async def count_annotations_at_commit(self, commit_id: uuid.UUID) -> int:
        """
        Count total annotations at a commit.

        Args:
            commit_id: Commit ID

        Returns:
            Number of annotations
        """
        return await self.camap_repo.count_annotations_at_commit(commit_id)

    async def count_samples_at_commit(self, commit_id: uuid.UUID) -> int:
        """
        Count unique samples with annotations at a commit.

        Args:
            commit_id: Commit ID

        Returns:
            Number of samples
        """
        return await self.camap_repo.count_samples_at_commit(commit_id)
