"""
System Service - Initialization and system-wide operations.
"""

from typing import Any, Dict, List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core import security
from saki_api.core.rbac.presets import init_preset_roles, get_role_by_name
from saki_api.models import User, UserSystemRole
from saki_api.schemas import UserCreate
from saki_api.services.user_service import UserService
from saki_api.repositories.user_repository import UserRepository


class SystemService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_status(self) -> Dict[str, bool]:
        result = await self.session.exec(select(User).limit(1))
        user = result.first()
        return {"initialized": user is not None}

    async def setup_system(self, user_in: UserCreate) -> User:
        # Initialize preset roles
        roles = await init_preset_roles(self.session)

        # Create first user
        user_data = user_in.model_dump(exclude={"password"})
        user_data["hashed_password"] = security.get_password_hash(user_in.password)
        user_data["is_active"] = True
        db_user = User.model_validate(user_data)
        self.session.add(db_user)
        await self.session.flush()

        # Assign super_admin role
        super_admin_role = roles.get("super_admin") or await get_role_by_name(self.session, "super_admin")
        if super_admin_role:
            user_role = UserSystemRole(user_id=db_user.id, role_id=super_admin_role.id)
            self.session.add(user_role)

        await self.session.commit()
        await self.session.refresh(db_user)
        return db_user

    async def build_user_read(self, user: User) -> Any:
        # Reuse existing user service builder for consistency
        repo = UserRepository(self.session)
        return await UserService(repo).build_user_read(user)

    @staticmethod
    def get_available_types() -> Dict[str, List[Dict[str, str]]]:
        """Return task and annotation system types for frontend options."""
        task_types = [
            {
                "value": "classification",
                "label": "Classification",
                "description": "Image classification task - assign one label per image",
            },
            {
                "value": "detection",
                "label": "Detection",
                "description": "Object detection task - locate and classify objects with bounding boxes",
            },
            {
                "value": "segmentation",
                "label": "Segmentation",
                "description": "Semantic segmentation task - pixel-level classification",
            },
        ]

        annotation_systems = [
            {
                "value": "classic",
                "label": "Classic Annotation",
                "description": "Standard image annotation with rectangles and OBB",
            },
            {
                "value": "fedo",
                "label": "FEDO Dual-View",
                "description": "Satellite electron energy data annotation with Time-Energy and L-ωd synchronized views",
            },
        ]

        return {
            "task_types": task_types,
            "annotation": annotation_systems,
        }
