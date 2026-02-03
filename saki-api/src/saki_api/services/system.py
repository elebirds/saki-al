"""
System Service - Initialization and system-wide operations.
"""

from typing import Dict, List

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import BadRequestAppException
from saki_api.core.rbac.presets import init_preset_roles
from saki_api.db.transaction import transactional
from saki_api.repositories.user_system_role import UserSystemRoleRepository
from saki_api.schemas import UserCreate, UserRead
from saki_api.services import UserService, RoleService


class SystemService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.user_service = UserService(session)
        self.role_service = RoleService(session)
        self.user_role_repo = UserSystemRoleRepository(session)

    async def get_status(self) -> Dict[str, bool]:
        return {"initialized": await self.is_init()}

    async def is_init(self) -> bool:
        return await self.user_service.has_any_user()

    @transactional
    async def setup_system(self, user_in: UserCreate) -> UserRead:
        """
        Initialize the system with the first superuser.
        
        This method:
        1. Creates all preset roles
        2. Creates the first user
        3. Assigns super_admin role to the first user
        
        Args:
            user_in: User creation data for the first superuser
            
        Returns:
            UserRead: Created superuser profile
            
        Raises:
            BadRequestAppException: If system is already initialized
        """
        if await self.is_init():
            raise BadRequestAppException("System already exists")

        # Initialize preset roles
        await init_preset_roles(self.session)

        # Create the first user
        user = await self.user_service.create(user_in, must_change_password=False)

        # Get super_admin role
        super_admin_role = await self.role_service.get_super_admin()
        if not super_admin_role:
            raise BadRequestAppException("super_admin role not found after initialization")

        from saki_api.schemas.user_system_role import UserSystemRoleCreate

        role_in = UserSystemRoleCreate(
            user_id=user.id,
            role_id=super_admin_role.id,
        )
        await self.user_role_repo.assign(role_in)

        return await self.user_service.get_profile_by_id(user.id)

    @staticmethod
    def get_available_types() -> Dict[str, List[Dict[str, str]]]:
        """Return task and annotation system types for frontend options."""
        task = [
            {
                "value": "classification",
                "label": "Classification",
                "description": "Image classification task - assign one label per image",
                "color": "purple",
            },
            {
                "value": "detection",
                "label": "Detection",
                "description": "Object detection task - locate and classify objects with bounding boxes",
                "color": "green",
            },
            {
                "value": "segmentation",
                "label": "Segmentation",
                "description": "Semantic segmentation task - pixel-level classification",
                "color": "yellow",
            },
        ]

        dataset = [
            {
                "value": "classic",
                "label": "Classic Annotation",
                "description": "Standard image annotation with rectangles and OBB",
                "color": "cyan",
            },
            {
                "value": "fedo",
                "label": "FEDO Dual-View",
                "description": "Satellite electron energy data annotation with Time-Energy and L-ωd synchronized views",
                "color": "purple",
            },
        ]

        return {
            "task": task,
            "dataset": dataset,
        }
