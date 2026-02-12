"""
Label Service - Business logic for Label operations.
"""

import uuid
from typing import List

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import DataAlreadyExistsAppException, NotFoundAppException
from saki_api.infra.db.transaction import transactional
from saki_api.modules.project.api.label import LabelCreate, LabelUpdate
from saki_api.modules.project.domain.label import Label
from saki_api.modules.project.repo import ProjectRepository
from saki_api.modules.project.repo.label import LabelRepository
from saki_api.modules.shared.application.crud_service import CrudServiceBase


class LabelService(CrudServiceBase[Label, LabelRepository, LabelCreate, LabelUpdate]):
    """
    Service for managing Labels.
    """

    def __init__(self, session: AsyncSession):
        super().__init__(Label, LabelRepository, session)
        self.session = session
        self.project_repo = ProjectRepository(session)

    @transactional
    async def create_label(self, schema: LabelCreate) -> Label:
        """
        Create a new label in a project.

        Args:
            schema: LabelCreate schema

        Returns:
            Created label

        Raises:
            NotFoundAppException: If project not found
            DataAlreadyExistsAppException: If label name already exists in project
        """
        # Verify project exists
        project = await self.project_repo.get_by_id(schema.project_id)
        if not project:
            raise NotFoundAppException(f"Project {schema.project_id} not found")

        # Check if label name already exists
        if await self.repository.name_exists(schema.project_id, schema.name):
            raise DataAlreadyExistsAppException(
                f"Label '{schema.name}' already exists in this project"
            )

        # Get next sort_order if not provided
        label_data = schema.model_dump()
        if label_data.get("sort_order", 0) == 0:
            max_order = await self.repository.get_max_sort_order(schema.project_id)
            label_data["sort_order"] = max_order + 1

        return await self.create(schema)

    @transactional
    async def update_label(
            self,
            label_id: uuid.UUID,
            schema: LabelUpdate,
    ) -> Label:
        """
        Update a label.

        Args:
            label_id: Label ID
            schema: LabelUpdate schema

        Returns:
            Updated label

        Raises:
            NotFoundAppException: If label not found
            DataAlreadyExistsAppException: If new name conflicts with existing label
        """
        label = await self.get_by_id_or_raise(label_id)

        # Check if name change conflicts
        if schema.name is not None and schema.name != label.name:
            if await self.repository.name_exists(label.project_id, schema.name, exclude_id=label_id):
                raise DataAlreadyExistsAppException(
                    f"Label '{schema.name}' already exists in this project"
                )

        return await self.update(label_id, schema.model_dump(exclude_unset=True))

    async def get_by_project(self, project_id: uuid.UUID) -> List[Label]:
        """
        Get all labels for a project, ordered by sort_order.

        Args:
            project_id: Project ID

        Returns:
            List of labels

        Raises:
            NotFoundAppException: If project not found
        """
        # Verify project exists
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise NotFoundAppException(f"Project {project_id} not found")

        return await self.repository.get_by_project(project_id)

    @transactional
    async def batch_create(
            self,
            project_id: uuid.UUID,
            labels: List[dict],
    ) -> List[Label]:
        """
        Batch create labels in a project.

        Args:
            project_id: Project ID
            labels: List of label data dictionaries

        Returns:
            List of created labels

        Raises:
            NotFoundAppException: If project not found
            DataAlreadyExistsAppException: If any label name conflicts
        """
        # Verify project exists
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise NotFoundAppException(f"Project {project_id} not found")

        # Check for name conflicts
        for label_data in labels:
            name = label_data.get("name")
            if name and await self.repository.name_exists(project_id, name):
                raise DataAlreadyExistsAppException(
                    f"Label '{name}' already exists in this project"
                )

        # Assign sort_order if not provided
        max_order = await self.repository.get_max_sort_order(project_id)
        for i, label_data in enumerate(labels):
            if "sort_order" not in label_data or label_data["sort_order"] == 0:
                label_data["sort_order"] = max_order + i + 1
            label_data["project_id"] = project_id

        return await self.repository.batch_create(labels)

    @transactional
    async def reorder(
            self,
            project_id: uuid.UUID,
            label_ids: List[uuid.UUID],
    ) -> List[Label]:
        """
        Reorder labels in a project.

        Args:
            project_id: Project ID
            label_ids: List of label IDs in new order

        Returns:
            List of updated labels

        Raises:
            NotFoundAppException: If project not found
        """
        # Verify project exists
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise NotFoundAppException(f"Project {project_id} not found")

        # Update sort_order for each label
        updated = []
        for i, label_id in enumerate(label_ids):
            label = await self.get_by_id(label_id)
            if label and label.project_id == project_id:
                label.sort_order = i + 1
                self.session.add(label)
                updated.append(label)

        await self.session.flush()
        for label in updated:
            await self.session.refresh(label)

        return updated
