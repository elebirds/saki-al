"""
System endpoints for initialization and runtime settings.
"""

import uuid
from typing import Any, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from saki_api.app.deps import SystemServiceDep, SystemSettingsServiceDep
from saki_api.modules.access.api.dependencies import get_current_user_id, require_permission
from saki_api.modules.access.domain.rbac import Permissions
from saki_api.modules.system.service.system import SystemService
from saki_api.modules.system.service.system_setting_keys import SystemSettingKeys
from saki_api.schemas import UserCreate, UserRead

router = APIRouter()


# ============================================================================
# Pydantic Models for API
# ============================================================================

class TypeInfo(BaseModel):
    """Information about a type option."""
    value: str
    label: str
    description: str
    color: str


class AvailableTypesResponse(BaseModel):
    """Response with all available types."""
    task_types: List[TypeInfo]
    dataset_types: List[TypeInfo]


class SystemStatusResponse(BaseModel):
    initialized: bool
    allow_self_register: bool


class SystemSettingOption(BaseModel):
    value: str
    label: str


class SystemSettingField(BaseModel):
    key: str
    group: str
    title: str
    description: str
    type: str
    default: Any
    editable: bool = True
    order: int = 0
    group_order: int = 0
    options: List[SystemSettingOption] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    ui: dict[str, Any] = Field(default_factory=dict)


class SystemSettingsBundleResponse(BaseModel):
    fields: List[SystemSettingField]
    values: dict[str, Any]


class SystemSettingsUpdateRequest(BaseModel):
    values: dict[str, Any]


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/status")
async def get_system_status(
        service: SystemServiceDep,
        settings_service: SystemSettingsServiceDep,
) -> SystemStatusResponse:
    """
    Check if the system is initialized (has at least one user).
    """
    status = await service.get_status()
    allow_self_register = await settings_service.get_bool(
        SystemSettingKeys.AUTH_ALLOW_SELF_REGISTER,
        default=False,
    )
    return SystemStatusResponse(
        initialized=bool(status.get("initialized")),
        allow_self_register=allow_self_register,
    )


@router.get("/types", response_model=AvailableTypesResponse)
def get_available_types() -> AvailableTypesResponse:
    """
    Get all available task types and annotation systems.
    Frontend should call this to populate dropdowns.
    """
    data = SystemService.get_available_types()
    return AvailableTypesResponse(
        task_types=[TypeInfo(**item) for item in data["task"]],
        dataset_types=[TypeInfo(**item) for item in data["dataset"]],
    )


@router.post("/setup", response_model=UserRead)
async def setup_system(
        user_in: UserCreate,
        service: SystemServiceDep
) -> UserRead:
    """
    Initialize the system with the first superuser.
    
    This endpoint:
    1. Creates all preset roles
    2. Creates the first user
    3. Assigns super_admin role to the first user
    """
    return await service.setup_system(user_in)


@router.get(
    "/settings/bundle",
    response_model=SystemSettingsBundleResponse,
    dependencies=[Depends(require_permission(Permissions.SYSTEM_SETTING_READ))],
)
async def get_system_settings_bundle(
        settings_service: SystemSettingsServiceDep,
) -> SystemSettingsBundleResponse:
    payload = await settings_service.get_bundle()
    return SystemSettingsBundleResponse.model_validate(payload)


@router.patch(
    "/settings",
    response_model=SystemSettingsBundleResponse,
    dependencies=[Depends(require_permission(Permissions.SYSTEM_SETTING_UPDATE))],
)
async def patch_system_settings(
        request: SystemSettingsUpdateRequest,
        settings_service: SystemSettingsServiceDep,
        user_id: uuid.UUID = Depends(get_current_user_id),
) -> SystemSettingsBundleResponse:
    await settings_service.update_values(request.values, updated_by=user_id)
    payload = await settings_service.get_bundle()
    return SystemSettingsBundleResponse.model_validate(payload)
