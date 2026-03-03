"""
Label Service - Business logic for Label operations.
"""

import uuid
from typing import List

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import BadRequestAppException, DataAlreadyExistsAppException, NotFoundAppException
from saki_api.infra.db.transaction import transactional
from saki_api.modules.project.api.label import LabelCreate, LabelUpdate
from saki_api.modules.project.domain.label import Label
from saki_api.modules.project.repo import ProjectRepository
from saki_api.modules.project.repo.label import LabelRepository
from saki_api.modules.runtime.repo.model_class_schema import ModelClassSchemaRepository
from saki_api.modules.shared.application.crud_service import CrudServiceBase


class LabelService(CrudServiceBase[Label, LabelRepository, LabelCreate, LabelUpdate]):
    """
    Service for managing Labels.
    """

    def __init__(self, session: AsyncSession):
        super().__init__(Label, LabelRepository, session)
        self.session = session
        self.project_repo = ProjectRepository(session)
        self.model_class_schema_repo = ModelClassSchemaRepository(session)

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

        # create 一律追加到末尾，排序变更统一走 reorder
        label_data = schema.model_dump()
        max_order = await self.repository.get_max_sort_order(schema.project_id)
        label_data["sort_order"] = max_order + 1

        return await self.repository.create(label_data)

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

        if schema.sort_order is not None:
            raise BadRequestAppException(
                "sort_order can only be changed via /projects/{project_id}/labels/reorder"
            )

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

        # batch create 也按输入顺序追加到末尾，忽略传入 sort_order
        max_order = await self.repository.get_max_sort_order(project_id)
        for i, label_data in enumerate(labels):
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

        labels = await self.repository.get_by_project(project_id)
        expected_ids = [item.id for item in labels]
        expected_set = set(expected_ids)
        received_ids = list(label_ids or [])

        if len(received_ids) != len(expected_ids):
            raise BadRequestAppException("label_ids must include all project labels exactly once")
        if len(set(received_ids)) != len(received_ids):
            raise BadRequestAppException("label_ids contains duplicated id")
        if set(received_ids) != expected_set:
            raise BadRequestAppException("label_ids must be a complete permutation of project label ids")

        if received_ids == expected_ids:
            return labels

        label_by_id = {item.id: item for item in labels}
        current_max = max((item.sort_order for item in labels), default=0)
        temp_base = current_max + len(labels) + 1000

        # 两阶段写入，避免 (project_id, sort_order) 唯一约束冲突
        for i, label_id in enumerate(received_ids, start=1):
            label = label_by_id[label_id]
            label.sort_order = temp_base + i
            self.session.add(label)
        await self.session.flush()

        for i, label_id in enumerate(received_ids, start=1):
            label = label_by_id[label_id]
            label.sort_order = i
            self.session.add(label)
        await self.session.flush()

        return await self.repository.get_by_project(project_id)

    @transactional
    async def delete_label(
            self,
            *,
            label_id: uuid.UUID,
            project_id: uuid.UUID | None = None,
    ) -> None:
        label = await self.get_by_id_or_raise(label_id)
        if project_id is not None and label.project_id != project_id:
            raise BadRequestAppException("Label not found in project")
        if await self.model_class_schema_repo.exists_by_label(label_id):
            raise BadRequestAppException(
                "label is referenced by model_class_schema and cannot be deleted"
            )

        deleted = await self.repository.delete(label_id)
        if not deleted:
            raise NotFoundAppException(f"Label {label_id} not found")

        await self._compact_sort_order(label.project_id)

    async def _compact_sort_order(self, project_id: uuid.UUID) -> None:
        labels = await self.repository.get_by_project(project_id)
        dirty = False
        for i, item in enumerate(labels, start=1):
            if item.sort_order != i:
                item.sort_order = i
                self.session.add(item)
                dirty = True
        if dirty:
            await self.session.flush()
