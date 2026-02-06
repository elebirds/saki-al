"""
Annotation Service - Business logic for Annotation operations.
"""

import logging
import uuid
from typing import List

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import NotFoundAppException, BadRequestAppException
from saki_api.db.transaction import transactional
from saki_api.models.l2.annotation import Annotation
from saki_api.repositories.annotation import AnnotationRepository
from saki_api.repositories.branch import BranchRepository
from saki_api.repositories.commit import CommitRepository
from saki_api.repositories.label import LabelRepository
from saki_api.repositories.project import ProjectRepository
from saki_api.repositories.sample import SampleRepository
from saki_api.schemas.annotation import AnnotationCreate
from saki_api.services.base import BaseService
from saki_api.utils.coordinate_converter import convert_annotation_data_to_backend, convert_annotation_data_to_frontend

logger = logging.getLogger(__name__)


class AnnotationService(BaseService[Annotation, AnnotationRepository, AnnotationCreate, dict]):
    """
    Service for managing Annotations.

    Annotations are immutable - modifications create new records with parent_id.
    """

    def __init__(self, session: AsyncSession):
        super().__init__(Annotation, AnnotationRepository, session)
        self.session = session
        self.project_repo = ProjectRepository(session)
        self.label_repo = LabelRepository(session)
        self.sample_repo = SampleRepository(session)
        self.branch_repo = BranchRepository(session)
        self.commit_repo = CommitRepository(session)

    @transactional
    async def create_annotation(self, schema: AnnotationCreate) -> Annotation:
        """
        Create a new annotation.

        Args:
            schema: AnnotationCreate schema

        Returns:
            Created annotation

        Raises:
            NotFoundAppException: If project, sample, or label not found
        """
        # Verify project exists
        project = await self.project_repo.get_by_id(schema.project_id)
        if not project:
            raise NotFoundAppException(f"Project {schema.project_id} not found")

        # Verify sample exists
        sample = await self.sample_repo.get_by_id(schema.sample_id)
        if not sample:
            raise NotFoundAppException(f"Sample {schema.sample_id} not found")

        # Verify label exists
        label = await self.label_repo.get_by_id(schema.label_id)
        if not label:
            raise NotFoundAppException(f"Label {schema.label_id} not found")

        # Verify label belongs to the same project
        if label.project_id != schema.project_id:
            raise BadRequestAppException("Label must belong to the same project")

        # Verify sample is in a dataset linked to the project
        dataset_ids = await self.project_repo.get_linked_dataset_ids(schema.project_id)
        if sample.dataset_id not in dataset_ids:
            raise BadRequestAppException(
                f"Sample {schema.sample_id} is not in any dataset linked to this project"
            )

        # If parent_id is provided, verify it exists
        if schema.parent_id:
            parent = await self.get_by_id(schema.parent_id)
            if not parent:
                raise NotFoundAppException(f"Parent annotation {schema.parent_id} not found")

        annotation_type = schema.type.value if hasattr(schema.type, "value") else str(schema.type)
        schema.data = convert_annotation_data_to_backend(annotation_type, schema.data)

        return await self.create(schema.model_dump())

    async def get_annotations_at_commit(
            self,
            commit_id: uuid.UUID,
            sample_id: uuid.UUID | None = None,
    ) -> List[Annotation]:
        """
        Get annotations for a specific commit.

        Args:
            commit_id: Commit ID
            sample_id: Optional sample ID to filter

        Returns:
            List of annotations visible at this commit
        """
        if sample_id:
            return await self.repository.get_by_commit_and_sample(commit_id, sample_id)
        return await self.repository.get_by_commit(commit_id)

    async def get_sample_annotations(self, sample_id: uuid.UUID) -> List[Annotation]:
        """
        Get all annotations for a sample (all versions).

        Args:
            sample_id: Sample ID

        Returns:
            List of all annotations for this sample
        """
        return await self.repository.get_by_sample(sample_id)

    async def get_project_annotations(self, project_id: uuid.UUID) -> List[Annotation]:
        """
        Get all annotations for a project.

        Args:
            project_id: Project ID

        Returns:
            List of annotations for this project
        """
        await self.project_repo.get_by_id_or_raise(project_id)
        return await self.repository.get_by_project(project_id)

    async def get_annotation_history(self, annotation_id: uuid.UUID, depth: int = 100) -> List:
        """
        Get annotation modification history by following parent_id chain.

        Args:
            annotation_id: Starting annotation ID
            depth: Maximum depth to traverse

        Returns:
            List of annotation history items
        """
        from saki_api.schemas.annotation import AnnotationHistoryItem

        annotations = await self.repository.get_history(annotation_id, depth)
        return [
            AnnotationHistoryItem(
                id=a.id,
                parent_id=a.parent_id,
                type=a.type,
                source=a.source,
                confidence=a.confidence,
                created_at=a.created_at,
                data=convert_annotation_data_to_frontend(
                    a.type.value if hasattr(a.type, "value") else str(a.type),
                    a.data,
                ),
            )
            for a in annotations
        ]

    async def get_by_lineage_id(self, lineage_id: uuid.UUID) -> List[Annotation]:
        """
        Get all annotations with a specific lineage_id (for version chain lookup).

        Args:
            lineage_id: Lineage ID

        Returns:
            List of annotations with this lineage_id
        """
        return await self.repository.get_by_lineage_id(lineage_id)

    async def count_by_project(self, project_id: uuid.UUID) -> int:
        """
        Count annotations for a project.

        Args:
            project_id: Project ID

        Returns:
            Number of annotations
        """
        return await self.repository.count_by_project(project_id)

    async def count_by_sample(self, sample_id: uuid.UUID) -> int:
        """
        Count annotations for a sample.

        Args:
            sample_id: Sample ID

        Returns:
            Number of annotations
        """
        return await self.repository.count_by_sample(sample_id)
