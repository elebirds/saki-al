"""
System Service - Initialization and system-wide operations.
"""

from typing import Any, Dict, List

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import BadRequestAppException
from saki_api.infra.db.transaction import transactional
from saki_api.modules.access.contracts import AccessMembershipGateway
from saki_api.modules.access.service.presets import init_preset_roles
from saki_api.modules.project.domain.annotation_policy import (
    DATASET_REQUIRED_ANNOTATION_TYPES,
    SUPPORTED_TASK_TYPES,
    TASK_ALLOWED_ANNOTATION_TYPES,
    TASK_DEFAULT_ANNOTATION_TYPES,
)
from saki_api.modules.access.service.role import RoleService
from saki_api.modules.access.service.user import UserService
from saki_api.modules.shared.modeling.enums import DatasetType, TaskType
from saki_api.schemas import UserCreate, UserRead


class SystemService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.user_service = UserService(session)
        self.role_service = RoleService(session)
        self.access_gateway = AccessMembershipGateway(session)

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

        await self.access_gateway.assign_system_role(
            user_id=user.id,
            role_id=super_admin_role.id,
        )

        return await self.user_service.get_profile_by_id(user.id)

    @staticmethod
    def get_available_types() -> Dict[str, List[Dict[str, Any]]]:
        """Return task and annotation system types for frontend options."""
        task = [
            {
                "value": "classification",
                "label": "Classification",
                "description": "Image classification task - assign one label per image",
                "color": "purple",
                "enabled": False,
                "allowed_annotation_types": [],
                "must_annotation_types": [],
                "banned_annotation_types": [item.value for item in TASK_ALLOWED_ANNOTATION_TYPES.get(TaskType.DETECTION, ())],
                # Backward compatible fields (deprecated)
                "annotation_types": [],
                "default_annotation_types": [],
            },
            {
                "value": "detection",
                "label": "Detection",
                "description": "Object detection task - locate and classify objects with bounding boxes",
                "color": "green",
                "enabled": True,
                "allowed_annotation_types": [item.value for item in TASK_ALLOWED_ANNOTATION_TYPES.get(TaskType.DETECTION, ())],
                "must_annotation_types": [],
                "banned_annotation_types": [],
                # Backward compatible fields (deprecated)
                "annotation_types": [item.value for item in TASK_ALLOWED_ANNOTATION_TYPES.get(TaskType.DETECTION, ())],
                "default_annotation_types": [item.value for item in TASK_DEFAULT_ANNOTATION_TYPES.get(TaskType.DETECTION, ())],
            },
            {
                "value": "segmentation",
                "label": "Segmentation",
                "description": "Semantic segmentation task - pixel-level classification",
                "color": "yellow",
                "enabled": False,
                "allowed_annotation_types": [],
                "must_annotation_types": [],
                "banned_annotation_types": [item.value for item in TASK_ALLOWED_ANNOTATION_TYPES.get(TaskType.DETECTION, ())],
                # Backward compatible fields (deprecated)
                "annotation_types": [],
                "default_annotation_types": [],
            },
        ]

        supported_task_values = {task_type.value for task_type in SUPPORTED_TASK_TYPES}
        for item in task:
            item["enabled"] = item["value"] in supported_task_values

        dataset = [
            {
                "value": "classic",
                "label": "Classic Annotation",
                "description": "Standard image annotation with rectangles and OBB",
                "color": "cyan",
                "allowed_annotation_types": [],
                "must_annotation_types": [],
                "banned_annotation_types": [],
            },
            {
                "value": "fedo",
                "label": "FEDO Dual-View",
                "description": "Satellite electron energy data annotation with Time-Energy and L-ωd synchronized views",
                "color": "purple",
                "allowed_annotation_types": [],
                "must_annotation_types": [
                    item.value for item in DATASET_REQUIRED_ANNOTATION_TYPES.get(DatasetType.FEDO, ())
                ],
                "banned_annotation_types": [],
            },
        ]

        return {
            "task": task,
            "dataset": dataset,
        }
