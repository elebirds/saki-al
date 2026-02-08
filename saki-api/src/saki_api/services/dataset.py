"""
Dataset Service.
"""

from loguru import logger
import uuid
from typing import List

from fastapi.params import Depends
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import DataAlreadyExistsAppException, NotFoundAppException, BadRequestAppException
from saki_api.core.rbac.dependencies import get_current_user_id
from saki_api.core.rbac.presets import DATASET_OWNER_ROLE_ID
from saki_api.db.transaction import transactional
from saki_api.models.l1.dataset import Dataset
from saki_api.models.rbac import ResourceType, Role, RoleType
from saki_api.models.rbac.resource_member import ResourceMember
from saki_api.repositories.dataset import DatasetRepository
from saki_api.repositories.query import Pagination
from saki_api.repositories.resource_member import ResourceMemberRepository
from saki_api.repositories.role import RoleRepository
from saki_api.schemas.dataset import DatasetCreate, DatasetUpdate
from saki_api.schemas.pagination import PaginationResponse
from saki_api.schemas.resource_member import ResourceMemberCreateRequest, ResourceMemberRead, \
    ResourceMemberUpdateRequest
from saki_api.services.base import BaseService



class DatasetService(BaseService[Dataset, DatasetRepository, DatasetCreate, DatasetUpdate]):
    """
    Service for managing Datasets.
    """

    def __init__(self, session: AsyncSession):
        super().__init__(Dataset, DatasetRepository, session)
        self.session = session
        self.resource_member_repo = ResourceMemberRepository(session)
        self.role_repo = RoleRepository(session)

    @transactional
    async def create_dataset(self, schema: DatasetCreate, owner_id: uuid.UUID) -> Dataset:
        """
        Create a new dataset with owner.
        
        Automatically assigns the creator as the first member with the owner role.
        Owner role is a system preset and doesn't need to be queried.
        """
        dataset_data = schema.model_dump()
        dataset_data["owner_id"] = owner_id
        created_dataset = await self.repository.create(dataset_data)

        # Assign owner role to the creator
        await self.resource_member_repo.assign_role(
            resource_type=ResourceType.DATASET,
            resource_id=created_dataset.id,
            user_id=owner_id,
            role_id=DATASET_OWNER_ROLE_ID,
        )

        return created_dataset

    async def list_datasets(
            self,
            user_id: uuid.UUID,
            pagination: Pagination,
    ) -> PaginationResponse[Dataset]:
        """List datasets available to a user with pagination."""
        return await self.repository.list_in_permission_paginated(user_id, pagination)

    # =========================================================================
    # Dataset Member Management
    # =========================================================================

    async def get_dataset_members(self, dataset_id: uuid.UUID) -> List[ResourceMemberRead]:
        """
        Get all members of a dataset with user and role information.
        
        Returns a list of dictionaries containing member, user, and role data.
        """
        # Verify dataset exists
        await self.get_by_id_or_raise(dataset_id)

        result = await self.resource_member_repo.list(
            filters=[
                ResourceMember.resource_type == ResourceType.DATASET,
                ResourceMember.resource_id == dataset_id
            ],
            joinedloads=[ResourceMember.user, ResourceMember.role]
        )

        return [ResourceMemberRead.model_validate(i) for i in result]

    @transactional
    async def add_dataset_member(
            self,
            dataset_id: uuid.UUID,
            member_data: ResourceMemberCreateRequest
    ) -> ResourceMember:
        """
        Add a member to a dataset.
        
        Args:
            dataset_id: The dataset ID
            member_data: User ID and role ID to assign
            
        Returns:
            The created ResourceMember
            
        Raises:
            ValueError: If dataset not found or user already a member
            BadRequestAppException: If trying to assign owner role
        """
        # Verify dataset exists
        await self.get_by_id_or_raise(dataset_id)

        # Prevent assigning owner role to new members
        if member_data.role_id == DATASET_OWNER_ROLE_ID:
            raise BadRequestAppException("Cannot assign owner role to members. Owner is determined by dataset creator.")

        # Check if member already exists
        existing = await self.resource_member_repo.get_by_user_and_resource(
            member_data.user_id,
            ResourceType.DATASET,
            dataset_id
        )
        if existing:
            raise DataAlreadyExistsAppException("User is already a member of this dataset")

        # Create member
        new_member = ResourceMember(
            resource_type=ResourceType.DATASET,
            resource_id=dataset_id,
            user_id=member_data.user_id,
            role_id=member_data.role_id,
        )
        created = await self.resource_member_repo.create(new_member.model_dump())
        return created

    @transactional
    async def update_dataset_member(
            self,
            dataset_id: uuid.UUID,
            user_id: uuid.UUID,
            member_data: ResourceMemberUpdateRequest,
    ) -> ResourceMember:
        """
        Update a dataset member's role.
        
        Prevents:
        - Updating the dataset owner's membership
        - Removing the last owner of the dataset
        - Assigning owner role to other users
        
        Args:
            dataset_id: The dataset ID
            user_id: The user ID whose role is being changed
            member_data: New role ID
            
        Returns:
            The updated ResourceMember
            
        Raises:
            NotFoundAppException: If member not found
            BadRequestAppException: If trying to update owner or assign owner role
        """
        # Verify dataset exists
        dataset = await self.get_by_id_or_raise(dataset_id)

        # Prevent updating the dataset owner's membership
        if user_id == dataset.owner_id:
            raise BadRequestAppException("Cannot modify the dataset owner's membership")

        # Prevent assigning owner role
        if member_data.role_id == DATASET_OWNER_ROLE_ID:
            raise BadRequestAppException("Cannot assign owner role to members. Owner is determined by dataset creator.")

        # Get existing member
        existing = await self.resource_member_repo.get_by_user_and_resource(
            user_id,
            ResourceType.DATASET,
            dataset_id
        )
        if not existing:
            raise NotFoundAppException("Member not found")

        # Update member
        updated = await self.resource_member_repo.update(
            existing.id,
            {"role_id": member_data.role_id}
        )
        if updated is None: raise BadRequestAppException("Failed to update member")
        return updated

    @transactional
    async def remove_dataset_member(
            self,
            dataset_id: uuid.UUID,
            user_id: uuid.UUID,
            current_user_id: uuid.UUID = Depends(get_current_user_id)
    ) -> None:
        """
        Remove a member from a dataset.
        
        Prevents removing the dataset owner.
        
        Args:
            dataset_id: The dataset ID
            user_id: The user ID to remove
            session: Database session (injected by @transactional)
            
        Raises:
            NotFoundAppException: If member not found
            BadRequestAppException: If trying to remove the dataset owner
        """
        # Verify dataset exists
        dataset = await self.get_by_id_or_raise(dataset_id)

        # Prevent removing the dataset owner
        if user_id == dataset.owner_id:
            raise BadRequestAppException("Cannot remove the dataset owner")

        if current_user_id == user_id:
            raise BadRequestAppException("Cannot remove yourself")

        # Get existing member
        existing = await self.resource_member_repo.get_by_user_and_resource(
            user_id,
            ResourceType.DATASET,
            dataset_id
        )
        if not existing:
            raise NotFoundAppException("Member not found")

        # Delete member
        await self.resource_member_repo.delete(existing.id)

    async def get_available_dataset_roles(self, dataset_id: uuid.UUID) -> List[Role]:
        """
        Get all roles that can be assigned to dataset members.
        
        Returns resource-level roles only.
        
        Args:
            dataset_id: The dataset ID (for consistency, though roles are global)
            
        Returns:
            List of available Role objects
            
        Raises:
            ValueError: If dataset not found
        """
        # Verify dataset exists
        await self.get_by_id_or_raise(dataset_id)

        # Get all resource roles
        roles = await self.session.exec(
            select(Role)
            .where(Role.type == RoleType.RESOURCE)
            .order_by(Role.name)
        )

        return list(roles.all())
