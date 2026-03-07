from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from saki_api.app.deps import ImportUploadServiceDep
from saki_api.modules.access.api.dependencies import get_current_user_id
from saki_api.modules.importing.schema import (
    ImportUploadAbortResponse,
    ImportUploadCompleteRequest,
    ImportUploadInitRequest,
    ImportUploadInitResponse,
    ImportUploadPartSignRequest,
    ImportUploadPartSignResponse,
    ImportUploadSessionResponse,
)

router = APIRouter()


@router.post("/uploads:init", response_model=ImportUploadInitResponse)
async def init_import_upload_session(
    *,
    payload: ImportUploadInitRequest,
    service: ImportUploadServiceDep,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> ImportUploadInitResponse:
    return await service.init_upload_session(user_id=current_user_id, payload=payload)


@router.post("/uploads/{session_id}/parts:sign", response_model=ImportUploadPartSignResponse)
async def sign_import_upload_parts(
    *,
    session_id: uuid.UUID,
    payload: ImportUploadPartSignRequest,
    service: ImportUploadServiceDep,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> ImportUploadPartSignResponse:
    return await service.sign_parts(
        user_id=current_user_id,
        session_id=session_id,
        payload=payload,
    )


@router.post("/uploads/{session_id}:complete", response_model=ImportUploadSessionResponse)
async def complete_import_upload_session(
    *,
    session_id: uuid.UUID,
    payload: ImportUploadCompleteRequest,
    service: ImportUploadServiceDep,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> ImportUploadSessionResponse:
    return await service.complete_upload(
        user_id=current_user_id,
        session_id=session_id,
        payload=payload,
    )


@router.post("/uploads/{session_id}:abort", response_model=ImportUploadAbortResponse)
async def abort_import_upload_session(
    *,
    session_id: uuid.UUID,
    service: ImportUploadServiceDep,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> ImportUploadAbortResponse:
    return await service.abort_upload(
        user_id=current_user_id,
        session_id=session_id,
    )


@router.get("/uploads/{session_id}", response_model=ImportUploadSessionResponse)
async def get_import_upload_session(
    *,
    session_id: uuid.UUID,
    service: ImportUploadServiceDep,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> ImportUploadSessionResponse:
    return await service.get_session_status(user_id=current_user_id, session_id=session_id)
