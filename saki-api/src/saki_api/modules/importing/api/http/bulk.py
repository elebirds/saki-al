from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile

from saki_api.app.deps import ImportServiceDep, TaskServiceDep
from saki_api.core.config import settings
from saki_api.core.exceptions import BadRequestAppException
from saki_api.modules.access.api.dependencies import get_current_user_id, require_permission
from saki_api.modules.access.domain.rbac import Permissions, ResourceType
from saki_api.modules.importing.schema import (
    AnnotationBulkRequest,
    AnnotationBulkSource,
    ImportImageEntry,
    ImportExecuteRequest,
    ImportTaskCreateResponse,
    SampleBulkImportRequest,
)
from saki_api.modules.importing.service.task_service import TaskService

dataset_router = APIRouter()
project_router = APIRouter()


def _task_response(task_id: uuid.UUID) -> ImportTaskCreateResponse:
    base = f"{settings.API_V1_STR}/imports/tasks/{task_id}"
    return ImportTaskCreateResponse(
        task_id=task_id,
        status="queued",
        stream_url=f"{base}/events?after_seq=0",
        status_url=base,
    )


@dataset_router.post(
    "/{dataset_id}/samples:bulk-upload",
    response_model=ImportTaskCreateResponse,
    dependencies=[Depends(require_permission(Permissions.SAMPLE_CREATE, ResourceType.DATASET, "dataset_id"))],
)
async def bulk_upload_samples(
    *,
    dataset_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    task_service: TaskServiceDep,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> ImportTaskCreateResponse:
    temp_dir = Path(tempfile.mkdtemp(prefix="saki-bulk-upload-"))
    staged_files: list[dict[str, str]] = []

    for index, file in enumerate(files):
        filename = str(file.filename or f"upload_{index}")
        local_path = temp_dir / f"{index:06d}_{Path(filename).name}"
        with local_path.open("wb") as dst:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
        staged_files.append(
            {
                "filename": filename,
                "path": str(local_path),
                "content_type": str(file.content_type or "application/octet-stream"),
            }
        )

    task = await task_service.create_task(
        mode="sample_bulk_upload",
        resource_type=ResourceType.DATASET.value,
        resource_id=dataset_id,
        user_id=current_user_id,
        payload={
            "dataset_id": str(dataset_id),
            "staged_files": staged_files,
            "temp_dir": str(temp_dir),
        },
    )
    await task_service.session.commit()

    def producer_factory(session):
        from saki_api.modules.project.service.sample_bulk import SampleBulkService

        async def _producer():
            service = SampleBulkService(session)
            try:
                async for event in service.iter_bulk_upload_local_files(dataset_id=dataset_id, files=staged_files):
                    yield event
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

        return _producer()

    TaskService.schedule_streaming_job(task_id=task.id, producer_factory=producer_factory)
    return _task_response(task.id)


@dataset_router.post(
    "/{dataset_id}/samples:bulk-import",
    response_model=ImportTaskCreateResponse,
    dependencies=[Depends(require_permission(Permissions.DATASET_IMPORT, ResourceType.DATASET, "dataset_id"))],
)
async def bulk_import_samples(
    *,
    dataset_id: uuid.UUID,
    payload: SampleBulkImportRequest,
    import_service: ImportServiceDep,
    task_service: TaskServiceDep,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> ImportTaskCreateResponse:
    if payload.preview_token:
        zip_asset_id, image_entries = await import_service.resolve_dataset_image_manifest(
            user_id=current_user_id,
            dataset_id=dataset_id,
            preview_token=payload.preview_token,
        )
        await import_service.consume_preview_token(payload.preview_token)
    else:
        if payload.zip_asset_id is None:
            raise BadRequestAppException("zip_asset_id is required when preview_token is not provided")
        if payload.image_entries:
            image_entries = payload.image_entries
        elif payload.image_paths:
            image_entries = [
                ImportImageEntry(
                    zip_entry_path=str(item),
                    resolved_sample_name=str(item),
                    original_relative_path=str(item),
                    collision_action="none",
                )
                for item in payload.image_paths
            ]
        else:
            raise BadRequestAppException("image_entries or image_paths is required when preview_token is not provided")
        zip_asset_id = payload.zip_asset_id

    task = await task_service.create_task(
        mode="sample_bulk_import",
        resource_type=ResourceType.DATASET.value,
        resource_id=dataset_id,
        user_id=current_user_id,
        payload={
            "dataset_id": str(dataset_id),
            "zip_asset_id": str(zip_asset_id),
            "image_entries": [item.model_dump(mode="json") for item in image_entries],
        },
    )
    await task_service.session.commit()

    def producer_factory(session):
        from saki_api.modules.project.service.sample_bulk import SampleBulkService

        service = SampleBulkService(session)
        return service.iter_bulk_import_zip_entries(
            dataset_id=dataset_id,
            zip_asset_id=zip_asset_id,
            image_entries=image_entries,
        )

    TaskService.schedule_streaming_job(task_id=task.id, producer_factory=producer_factory)
    return _task_response(task.id)


@project_router.post(
    "/{project_id}/annotations:bulk",
    response_model=ImportTaskCreateResponse,
    dependencies=[
        Depends(require_permission(Permissions.COMMIT_CREATE, ResourceType.PROJECT, "project_id")),
        Depends(require_permission(Permissions.ANNOTATE, ResourceType.PROJECT, "project_id")),
    ],
)
async def bulk_annotations(
    *,
    project_id: uuid.UUID,
    payload: AnnotationBulkRequest,
    import_service: ImportServiceDep,
    task_service: TaskServiceDep,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
) -> ImportTaskCreateResponse:
    if payload.source == AnnotationBulkSource.IMPORT_PREVIEW:
        if not payload.preview_token:
            raise BadRequestAppException("preview_token is required when source=import_preview")
        return await import_service.start_project_annotations_execute(
            user_id=current_user_id,
            project_id=project_id,
            request=ImportExecuteRequest(
                preview_token=payload.preview_token,
                conflict_strategy=payload.conflict_strategy,
                confirm_create_labels=payload.confirm_create_labels,
            ),
        )

    if not payload.annotations:
        raise BadRequestAppException("annotations is required when source=direct")

    task = await task_service.create_task(
        mode="annotation_bulk_save",
        resource_type=ResourceType.PROJECT.value,
        resource_id=project_id,
        user_id=current_user_id,
        payload={
            "project_id": str(project_id),
            "branch_name": payload.branch_name,
            "commit_message": payload.commit_message,
            "annotation_count": len(payload.annotations),
        },
    )
    await task_service.session.commit()

    def producer_factory(session):
        from saki_api.modules.project.service.annotation_bulk import AnnotationBulkService

        service = AnnotationBulkService(session)
        return service.iter_bulk_save_annotations(
            project_id=project_id,
            branch_name=payload.branch_name,
            commit_message=payload.commit_message,
            annotation_changes=payload.annotations,
            author_id=current_user_id,
        )

    TaskService.schedule_streaming_job(task_id=task.id, producer_factory=producer_factory)
    return _task_response(task.id)
