"""
Label Repository - Data access layer for Label operations.
"""

import uuid
from typing import List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.project.domain.label import Label


class LabelRepository(BaseRepository[Label]):
    """Repository for Label data access."""

    def __init__(self, session: AsyncSession):
        super().__init__(Label, session)

    async def get_by_project(self, project_id: uuid.UUID) -> List[Label]:
        """
        Get all labels for a project, ordered by sort_order.

        Args:
            project_id: Project ID

        Returns:
            List of labels ordered by sort_order
        """
        return await self.list(
            filters=[Label.project_id == project_id],
            order_by=[Label.sort_order, Label.created_at]
        )

    async def get_by_project_and_name(
            self, project_id: uuid.UUID, name: str
    ) -> Label | None:
        """
        Get a label by project and name.

        Args:
            project_id: Project ID
            name: Label name

        Returns:
            Label if found, None otherwise
        """
        return await self.get_one(
            filters=[Label.project_id == project_id, Label.name == name]
        )

    async def get_max_sort_order(self, project_id: uuid.UUID) -> int:
        """
        Get the maximum sort_order for a project.

        Args:
            project_id: Project ID

        Returns:
            Maximum sort_order value, or 0 if no labels exist
        """
        from sqlalchemy import func
        stmt = select(func.coalesce(func.max(Label.sort_order), 0)).where(
            Label.project_id == project_id
        )
        result = await self.session.exec(stmt)
        return result.one() or 0

    async def name_exists(self, project_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None) -> bool:
        """
        Check if a label name exists in a project.

        Args:
            project_id: Project ID
            name: Label name
            exclude_id: Optional label ID to exclude from check (for updates)

        Returns:
            True if name exists, False otherwise
        """
        filters = [Label.project_id == project_id, Label.name == name]
        if exclude_id:
            filters.append(Label.id != exclude_id)
        return await self.exists(filters)

    async def batch_create(self, labels: List[dict]) -> List[Label]:
        """
        Batch create labels.

        Args:
            labels: List of label data dictionaries

        Returns:
            List of created labels
        """
        created = []
        for label_data in labels:
            label = Label(**label_data)
            self.session.add(label)
            created.append(label)
        await self.session.flush()
        for label in created:
            await self.session.refresh(label)
        return created
