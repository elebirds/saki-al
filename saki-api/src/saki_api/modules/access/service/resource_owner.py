"""
Resource Owner Service - Unified interface for checking resource ownership.

Provides a unified way to check if a user owns a resource, regardless of resource type.
This allows easy extension when new resource types are added.
"""

import uuid
from typing import Protocol

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.modules.access.domain.rbac.enums import ResourceType
from saki_api.modules.project.contracts import ProjectReadGateway


class ResourceOwnerChecker(Protocol):
    """Protocol for checking resource ownership."""

    async def is_owner(self, resource_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """
        Check if a user is the owner of a resource.
        
        Args:
            resource_id: Resource ID
            user_id: User ID
            
        Returns:
            True if user is owner, False otherwise
        """
        ...


class ResourceOwnerService:
    """
    Service for checking resource ownership across different resource types.
    
    Provides a unified interface that delegates to specific repository methods.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.project_gateway = ProjectReadGateway(session)
        # Add other resource repositories here as they are created
        # self.project_repo = ProjectRepository(session)

    async def is_owner(
            self,
            resource_type: ResourceType,
            resource_id: uuid.UUID,
            user_id: uuid.UUID,
    ) -> bool:
        """
        Check if a user is the owner of a resource.
        
        Args:
            resource_type: Resource type enum
            resource_id: Resource ID
            user_id: User ID
            
        Returns:
            True if user is owner, False otherwise
        """
        if resource_type == ResourceType.DATASET:
            return await self.project_gateway.is_dataset_owner(resource_id, user_id)

        # Add other resource types here as they are implemented
        # elif resource_type == ResourceType.PROJECT:
        #     return await self.project_repo.is_owner(resource_id, user_id)

        return False
