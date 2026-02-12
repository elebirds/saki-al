"""
Annotation Repository - Data access layer for Annotation operations.
"""

import uuid
from typing import List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.annotation.annotation import Annotation
from saki_api.models.annotation.camap import CommitAnnotationMap
from saki_api.repositories.base import BaseRepository


class AnnotationRepository(BaseRepository[Annotation]):
    """Repository for Annotation data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(Annotation, session)

    async def get_by_sample(self, sample_id: uuid.UUID) -> List[Annotation]:
        """
        Get all annotations for a sample (all versions).

        Args:
            sample_id: Sample ID

        Returns:
            List of all annotations for this sample
        """
        return await self.list(
            filters=[Annotation.sample_id == sample_id],
            order_by=[Annotation.created_at]
        )

    async def get_by_project(self, project_id: uuid.UUID) -> List[Annotation]:
        """
        Get all annotations for a project.

        Args:
            project_id: Project ID

        Returns:
            List of annotations for this project
        """
        return await self.list(
            filters=[Annotation.project_id == project_id],
            order_by=[Annotation.sample_id, Annotation.created_at]
        )

    async def get_by_commit_and_sample(
            self,
            commit_id: uuid.UUID,
            sample_id: uuid.UUID,
    ) -> List[Annotation]:
        """
        Get annotations for a sample at a specific commit (via CAMap).

        Args:
            commit_id: Commit ID
            sample_id: Sample ID

        Returns:
            List of annotations visible at this commit
        """
        # Get annotation IDs from CAMap
        statement = select(CommitAnnotationMap.annotation_id).where(
            CommitAnnotationMap.commit_id == commit_id,
            CommitAnnotationMap.sample_id == sample_id,
        )
        result = await self.session.exec(statement)
        annotation_ids = list(result.all())

        if not annotation_ids:
            return []

        # Fetch annotations by IDs
        annotations = []
        for ann_id in annotation_ids:
            ann = await self.get_by_id(ann_id)
            if ann:
                annotations.append(ann)

        return annotations

    async def get_by_commit(
            self,
            commit_id: uuid.UUID,
    ) -> List[Annotation]:
        """
        Get all annotations for a specific commit (via CAMap).

        Args:
            commit_id: Commit ID

        Returns:
            List of all annotations visible at this commit
        """
        # Get annotation IDs from CAMap
        statement = select(
            CommitAnnotationMap.annotation_id,
            CommitAnnotationMap.sample_id,
        ).where(
            CommitAnnotationMap.commit_id == commit_id,
        )
        result = await self.session.exec(statement)
        mappings = result.all()

        if not mappings:
            return []

        # Fetch annotations by IDs
        annotation_ids = [m[0] for m in mappings]
        annotations = []
        for ann_id in annotation_ids:
            ann = await self.get_by_id(ann_id)
            if ann:
                annotations.append(ann)

        return annotations

    async def get_history(self, annotation_id: uuid.UUID, depth: int = 100) -> List[Annotation]:
        """
        Get annotation modification history by following parent_id chain.

        Args:
            annotation_id: Starting annotation ID
            depth: Maximum depth to traverse

        Returns:
            List of annotations from oldest to newest
        """
        history = []
        current_id = annotation_id
        count = 0

        while current_id and count < depth:
            annotation = await self.get_by_id(current_id)
            if not annotation:
                break
            history.insert(0, annotation)  # Prepend to get chronological order
            current_id = annotation.parent_id
            count += 1

        return history

    async def get_by_label(self, label_id: uuid.UUID) -> List[Annotation]:
        """
        Get all annotations with a specific label.

        Args:
            label_id: Label ID

        Returns:
            List of annotations with this label
        """
        return await self.list(
            filters=[Annotation.label_id == label_id],
            order_by=[Annotation.created_at.desc()]
        )

    async def get_by_lineage_id(self, lineage_id: uuid.UUID) -> List[Annotation]:
        """
        Get all annotations with a specific lineage_id (for version chain lookup).

        Args:
            lineage_id: Lineage ID

        Returns:
            List of annotations with this lineage_id
        """
        return await self.list(
            filters=[Annotation.lineage_id == lineage_id],
            order_by=[Annotation.created_at]
        )

    async def count_by_project(self, project_id: uuid.UUID) -> int:
        """
        Count annotations for a project.

        Args:
            project_id: Project ID

        Returns:
            Number of annotations
        """
        from sqlalchemy import func

        statement = select(func.count()).select_from(
            select(Annotation).where(Annotation.project_id == project_id).subquery()
        )
        result = await self.session.exec(statement)
        return result.one() or 0

    async def count_by_sample(self, sample_id: uuid.UUID) -> int:
        """
        Count annotations for a sample.

        Args:
            sample_id: Sample ID

        Returns:
            Number of annotations
        """
        from sqlalchemy import func

        statement = select(func.count()).select_from(
            select(Annotation).where(Annotation.sample_id == sample_id).subquery()
        )
        result = await self.session.exec(statement)
        return result.one() or 0
