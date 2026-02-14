"""
Model registry endpoints.
"""

import uuid
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.app.deps import ModelServiceDep
from saki_api.core.exceptions import ForbiddenAppException
from saki_api.infra.db.session import get_session
from saki_api.modules.access.api.dependencies import get_current_user_id
from saki_api.modules.access.service.permission_checker import PermissionChecker
from saki_api.modules.runtime.api.model import (
    ModelRegisterFromRoundRequest,
    ModelRead,
    ModelPromoteRequest,
    ModelArtifactDownloadResponse,
)
from saki_api.modules.shared.modeling import Permissions, ResourceType

router = APIRouter()


async def _ensure_project_perm(
        *,
        session: AsyncSession,
        current_user_id: uuid.UUID,
        project_id: uuid.UUID,
        required: str,
) -> None:
    checker = PermissionChecker(session)
    allowed = await checker.check(
        user_id=current_user_id,
        permission=required,
        resource_type=ResourceType.PROJECT,
        resource_id=str(project_id),
    )
    if not allowed:
        fallback = Permissions.PROJECT_UPDATE if required == Permissions.MODEL_MANAGE else Permissions.PROJECT_READ
        allowed = await checker.check(
            user_id=current_user_id,
            permission=fallback,
            resource_type=ResourceType.PROJECT,
            resource_id=str(project_id),
        )
    if not allowed:
        raise ForbiddenAppException(f"Permission denied: {required}")


@router.post("/projects/{project_id}/models:register-from-round", response_model=ModelRead)
async def register_model_from_round(
        *,
        project_id: uuid.UUID,
        payload: ModelRegisterFromRoundRequest,
        model_service: ModelServiceDep,
        session: AsyncSession = Depends(get_session),
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=project_id,
        required=Permissions.MODEL_MANAGE,
    )
    model = await model_service.register_from_round(
        project_id=project_id,
        round_id=payload.round_id,
        created_by=current_user_id,
        name=payload.name,
        version_tag=payload.version_tag,
        status=payload.status,
    )
    return ModelRead.model_validate(model)


@router.get("/projects/{project_id}/models", response_model=List[ModelRead])
async def list_project_models(
        *,
        project_id: uuid.UUID,
        limit: int = Query(default=100, ge=1, le=1000),
        model_service: ModelServiceDep,
        session: AsyncSession = Depends(get_session),
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=project_id,
        required=Permissions.MODEL_READ,
    )
    models = await model_service.list_by_project(project_id=project_id, limit=limit)
    return [ModelRead.model_validate(item) for item in models]


@router.post("/models/{model_id}:promote", response_model=ModelRead)
async def promote_model(
        *,
        model_id: uuid.UUID,
        payload: ModelPromoteRequest,
        model_service: ModelServiceDep,
        session: AsyncSession = Depends(get_session),
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    model = await model_service.get_by_id_or_raise(model_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=model.project_id,
        required=Permissions.MODEL_MANAGE,
    )
    updated = await model_service.promote(model_id=model_id, target_status=payload.status)
    return ModelRead.model_validate(updated)


@router.get("/models/{model_id}/artifacts/{artifact_name}:download-url", response_model=ModelArtifactDownloadResponse)
async def get_model_artifact_download_url(
        *,
        model_id: uuid.UUID,
        artifact_name: str,
        expires_in_hours: int = Query(default=2, ge=1, le=24),
        model_service: ModelServiceDep,
        session: AsyncSession = Depends(get_session),
        current_user_id: uuid.UUID = Depends(get_current_user_id),
):
    model = await model_service.get_by_id_or_raise(model_id)
    await _ensure_project_perm(
        session=session,
        current_user_id=current_user_id,
        project_id=model.project_id,
        required=Permissions.MODEL_READ,
    )
    url = await model_service.get_artifact_download_url(
        model_id=model_id,
        artifact_name=artifact_name,
        expires_in_hours=expires_in_hours,
    )
    return ModelArtifactDownloadResponse(
        model_id=model_id,
        artifact_name=artifact_name,
        download_url=url,
        expires_in_hours=expires_in_hours,
    )
