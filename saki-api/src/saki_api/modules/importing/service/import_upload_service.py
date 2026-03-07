from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.config import settings
from saki_api.core.exceptions import BadRequestAppException, ForbiddenAppException, NotFoundAppException
from saki_api.infra.storage.provider import StorageError, get_storage_provider
from saki_api.modules.access.domain.rbac import Permissions, ResourceType
from saki_api.modules.access.service.permission_checker import PermissionChecker
from saki_api.modules.importing.domain import ImportUploadSessionStatus, ImportUploadStrategy
from saki_api.modules.importing.repo import ImportUploadSessionRepository
from saki_api.modules.importing.schema import (
    ImportUploadAbortResponse,
    ImportUploadCompleteRequest,
    ImportUploadInitRequest,
    ImportUploadInitResponse,
    ImportUploadPartSignRequest,
    ImportUploadPartSignResponse,
    ImportUploadPartSignedItem,
    ImportUploadSessionResponse,
)
from saki_api.modules.system.service.system_setting_keys import SystemSettingKeys
from saki_api.modules.system.service.system_settings import SystemSettingsService


_SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")
_SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class ImportUploadService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ImportUploadSessionRepository(session)
        self.storage = get_storage_provider()
        self.system_settings = SystemSettingsService(session)

    async def init_upload_session(
        self,
        *,
        user_id: uuid.UUID,
        payload: ImportUploadInitRequest,
    ) -> ImportUploadInitResponse:
        await self._expire_stale_sessions()

        resource_type = self._parse_resource_type(payload.resource_type)
        await self._ensure_mode_permission(
            user_id=user_id,
            mode=payload.mode,
            resource_type=resource_type,
            resource_id=payload.resource_id,
        )

        filename = str(payload.filename or "").strip()
        if not filename:
            raise BadRequestAppException("filename is required")
        if not filename.lower().endswith(".zip"):
            raise BadRequestAppException("Only ZIP archives are supported")

        size = int(payload.size or 0)
        if size <= 0:
            raise BadRequestAppException("size must be > 0")
        max_zip_bytes = await self._get_import_max_zip_bytes()
        if size > max_zip_bytes:
            raise BadRequestAppException(
                f"ZIP size exceeds limit ({size} > {max_zip_bytes})"
            )

        file_sha256 = self._normalize_file_sha256(payload.file_sha256)

        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=max(1, int(settings.IMPORT_UPLOAD_SESSION_TTL_MINUTES)))

        if file_sha256:
            reusable = await self.repo.find_latest_reusable_uploaded_session(
                user_id=user_id,
                file_sha256=file_sha256,
                size=size,
                now=now,
            )
            if reusable:
                can_reuse = False
                try:
                    stat = self.storage.head_object(reusable.object_key)
                    can_reuse = int(stat.size or 0) == size
                except StorageError:
                    can_reuse = False

                if can_reuse:
                    row = await self.repo.create(
                        {
                            "user_id": user_id,
                            "mode": payload.mode,
                            "resource_type": resource_type.value,
                            "resource_id": payload.resource_id,
                            "filename": filename,
                            "size": size,
                            "content_type": str(payload.content_type or "application/zip"),
                            "file_sha256": file_sha256,
                            "object_key": reusable.object_key,
                            "bucket": reusable.bucket or settings.MINIO_BUCKET_NAME,
                            "strategy": reusable.strategy,
                            "multipart_upload_id": None,
                            "status": ImportUploadSessionStatus.UPLOADED.value,
                            "uploaded_size": size,
                            "expires_at": expires_at,
                            "completed_at": now,
                            "meta_info": {
                                "reuse_hit": True,
                                "reuse_from_session_id": str(reusable.id),
                            },
                        }
                    )
                    await self.session.commit()
                    return ImportUploadInitResponse(
                        session_id=row.id,
                        strategy=ImportUploadStrategy(str(row.strategy)),
                        status=ImportUploadSessionStatus.UPLOADED,
                        reuse_hit=True,
                        object_key=row.object_key,
                        expires_at=expires_at,
                        part_size=int(settings.IMPORT_UPLOAD_PART_SIZE_BYTES),
                        upload_id=None,
                        url=None,
                        headers={},
                    )

        strategy = (
            ImportUploadStrategy.MULTIPART.value
            if size >= int(settings.IMPORT_UPLOAD_MULTIPART_THRESHOLD_BYTES)
            else ImportUploadStrategy.SINGLE_PUT.value
        )

        object_key = self._build_object_key(
            user_id=user_id,
            mode=payload.mode,
            filename=filename,
        )

        upload_id: str | None = None
        if strategy == ImportUploadStrategy.MULTIPART.value:
            try:
                upload_id = self.storage.init_multipart_upload(
                    object_name=object_key,
                    content_type=payload.content_type,
                )
            except StorageError as exc:
                raise BadRequestAppException(f"failed to init multipart upload: {exc}") from exc

        row = await self.repo.create(
            {
                "user_id": user_id,
                "mode": payload.mode,
                "resource_type": resource_type.value,
                "resource_id": payload.resource_id,
                "filename": filename,
                "size": size,
                "content_type": str(payload.content_type or "application/zip"),
                "file_sha256": file_sha256,
                "object_key": object_key,
                "bucket": settings.MINIO_BUCKET_NAME,
                "strategy": strategy,
                "multipart_upload_id": upload_id,
                "status": ImportUploadSessionStatus.INITIATED.value,
                "uploaded_size": 0,
                "expires_at": expires_at,
                "meta_info": {},
            }
        )
        await self.session.commit()

        put_url: str | None = None
        if strategy == ImportUploadStrategy.SINGLE_PUT.value:
            try:
                put_url = self.storage.get_presigned_put_url(
                    object_name=object_key,
                    expires_delta=timedelta(minutes=max(1, int(settings.IMPORT_UPLOAD_SESSION_TTL_MINUTES))),
                )
            except StorageError as exc:
                raise BadRequestAppException(f"failed to create upload url: {exc}") from exc

        return ImportUploadInitResponse(
            session_id=row.id,
            strategy=ImportUploadStrategy(strategy),
            status=ImportUploadSessionStatus.INITIATED,
            reuse_hit=False,
            object_key=object_key,
            expires_at=expires_at,
            part_size=int(settings.IMPORT_UPLOAD_PART_SIZE_BYTES),
            upload_id=upload_id,
            url=put_url,
            headers={},
        )

    async def sign_parts(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        payload: ImportUploadPartSignRequest,
    ) -> ImportUploadPartSignResponse:
        await self._expire_stale_sessions()

        row = await self._get_owned_session(session_id=session_id, user_id=user_id)
        self._ensure_not_expired(row)

        if row.strategy != ImportUploadStrategy.MULTIPART.value:
            raise BadRequestAppException("session strategy is not multipart")
        if not row.multipart_upload_id:
            raise BadRequestAppException("multipart upload id missing")
        if row.status not in {
            ImportUploadSessionStatus.INITIATED.value,
            ImportUploadSessionStatus.UPLOADING.value,
        }:
            raise BadRequestAppException(f"upload session is not signable: {row.status}")

        numbers = sorted({int(item) for item in payload.part_numbers if int(item) > 0})
        if not numbers:
            raise BadRequestAppException("part_numbers is required")
        if len(numbers) > int(settings.IMPORT_UPLOAD_MAX_PARTS_PER_SIGN):
            raise BadRequestAppException(
                f"too many part numbers ({len(numbers)} > {settings.IMPORT_UPLOAD_MAX_PARTS_PER_SIGN})"
            )

        signed: list[ImportUploadPartSignedItem] = []
        for number in numbers:
            try:
                url = self.storage.presign_upload_part(
                    object_name=row.object_key,
                    upload_id=row.multipart_upload_id,
                    part_number=number,
                    expires_delta=timedelta(minutes=max(1, int(settings.IMPORT_UPLOAD_SESSION_TTL_MINUTES))),
                )
            except StorageError as exc:
                raise BadRequestAppException(f"failed to sign part {number}: {exc}") from exc
            signed.append(ImportUploadPartSignedItem(part_number=number, url=url, headers={}))

        row.status = ImportUploadSessionStatus.UPLOADING.value
        await self.session.commit()

        return ImportUploadPartSignResponse(
            session_id=row.id,
            upload_id=row.multipart_upload_id,
            parts=signed,
        )

    async def complete_upload(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        payload: ImportUploadCompleteRequest,
    ) -> ImportUploadSessionResponse:
        await self._expire_stale_sessions()

        row = await self._get_owned_session(session_id=session_id, user_id=user_id)
        self._ensure_not_expired(row)

        if row.status in {ImportUploadSessionStatus.ABORTED.value, ImportUploadSessionStatus.CONSUMED.value}:
            raise BadRequestAppException(f"upload session is {row.status}")

        if row.strategy == ImportUploadStrategy.MULTIPART.value:
            if not row.multipart_upload_id:
                raise BadRequestAppException("multipart upload id missing")
            if not payload.parts:
                raise BadRequestAppException("parts is required for multipart upload")
            sorted_parts = sorted(payload.parts, key=lambda item: int(item.part_number))
            try:
                self.storage.complete_multipart_upload(
                    object_name=row.object_key,
                    upload_id=row.multipart_upload_id,
                    parts=[(int(item.part_number), str(item.etag)) for item in sorted_parts],
                )
            except StorageError as exc:
                raise BadRequestAppException(f"failed to complete multipart upload: {exc}") from exc

        try:
            stat = self.storage.head_object(row.object_key)
        except StorageError as exc:
            raise BadRequestAppException(f"uploaded object not found: {exc}") from exc

        actual_size = int(stat.size or 0)
        expected_size = int(payload.size or 0)
        if expected_size <= 0:
            raise BadRequestAppException("size must be > 0")
        if actual_size != expected_size:
            raise BadRequestAppException(f"size mismatch (uploaded={actual_size}, expected={expected_size})")
        if actual_size != int(row.size):
            raise BadRequestAppException(f"size mismatch (uploaded={actual_size}, session={row.size})")

        row.status = ImportUploadSessionStatus.UPLOADED.value
        row.uploaded_size = actual_size
        row.completed_at = datetime.now(UTC)
        row.error = None
        await self.session.commit()

        return self._serialize_session(row)

    async def abort_upload(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
    ) -> ImportUploadAbortResponse:
        await self._expire_stale_sessions()

        row = await self._get_owned_session(session_id=session_id, user_id=user_id)

        if row.strategy == ImportUploadStrategy.MULTIPART.value and row.multipart_upload_id:
            try:
                self.storage.abort_multipart_upload(
                    object_name=row.object_key,
                    upload_id=row.multipart_upload_id,
                )
            except StorageError:
                # best effort
                pass

        if row.status != ImportUploadSessionStatus.CONSUMED.value:
            await self._delete_object_if_unreferenced(
                object_key=row.object_key,
                exclude_session_id=row.id,
            )

        row.status = ImportUploadSessionStatus.ABORTED.value
        row.error = "aborted by user"
        await self.session.commit()

        return ImportUploadAbortResponse(
            session_id=row.id,
            status=ImportUploadSessionStatus.ABORTED,
        )

    async def get_session_status(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
    ) -> ImportUploadSessionResponse:
        await self._expire_stale_sessions()
        row = await self._get_owned_session(session_id=session_id, user_id=user_id)
        return self._serialize_session(row)

    async def resolve_uploaded_session(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        expected_mode: str,
        expected_resource_type: ResourceType,
        expected_resource_id: uuid.UUID,
        consume: bool = False,
    ):
        await self._expire_stale_sessions()

        row = await self._get_owned_session(session_id=session_id, user_id=user_id)
        self._ensure_not_expired(row)

        if row.status != ImportUploadSessionStatus.UPLOADED.value:
            raise BadRequestAppException(f"upload session is not uploaded: {row.status}")
        if row.mode != expected_mode:
            raise BadRequestAppException("upload session mode mismatch")
        if row.resource_type != expected_resource_type.value:
            raise BadRequestAppException("upload session resource type mismatch")
        if row.resource_id != expected_resource_id:
            raise BadRequestAppException("upload session resource id mismatch")

        if consume:
            row.status = ImportUploadSessionStatus.CONSUMED.value
            await self.session.commit()
        return row

    async def _get_owned_session(self, *, session_id: uuid.UUID, user_id: uuid.UUID):
        row = await self.repo.get(session_id)
        if not row:
            raise NotFoundAppException(f"upload session {session_id} not found")
        if row.user_id != user_id:
            raise ForbiddenAppException("upload session does not belong to current user")
        return row

    @staticmethod
    def _parse_resource_type(raw: str) -> ResourceType:
        value = str(raw or "").strip().lower()
        try:
            return ResourceType(value)
        except ValueError as exc:
            raise BadRequestAppException(f"invalid resource_type: {raw}") from exc

    @staticmethod
    def _normalize_file_sha256(raw: str | None) -> str | None:
        if raw is None:
            return None
        value = str(raw).strip().lower()
        if not value:
            return None
        if not _SHA256_HEX_RE.fullmatch(value):
            raise BadRequestAppException("file_sha256 must be 64-char hex string")
        return value

    async def _ensure_mode_permission(
        self,
        *,
        user_id: uuid.UUID,
        mode: str,
        resource_type: ResourceType,
        resource_id: uuid.UUID,
    ) -> None:
        checker = PermissionChecker(self.session)
        mode_key = str(mode or "").strip()

        if mode_key == "dataset_images":
            if resource_type != ResourceType.DATASET:
                raise BadRequestAppException("dataset_images mode requires resource_type=dataset")
            allowed = await checker.check(
                user_id=user_id,
                permission=Permissions.DATASET_IMPORT,
                resource_type=ResourceType.DATASET,
                resource_id=str(resource_id),
            )
            if not allowed:
                raise ForbiddenAppException("Permission denied: dataset:import:assigned")
            return

        if mode_key in {"project_annotations", "project_associated"}:
            if resource_type != ResourceType.PROJECT:
                raise BadRequestAppException(f"{mode_key} mode requires resource_type=project")
            can_commit = await checker.check(
                user_id=user_id,
                permission=Permissions.COMMIT_CREATE,
                resource_type=ResourceType.PROJECT,
                resource_id=str(resource_id),
            )
            can_annotate = await checker.check(
                user_id=user_id,
                permission=Permissions.ANNOTATE,
                resource_type=ResourceType.PROJECT,
                resource_id=str(resource_id),
            )
            if not (can_commit and can_annotate):
                raise ForbiddenAppException("Permission denied: project import requires commit+annotate")
            return

        raise BadRequestAppException(f"unsupported upload mode: {mode_key}")

    @staticmethod
    def _build_object_key(*, user_id: uuid.UUID, mode: str, filename: str) -> str:
        safe_name = _SAFE_FILENAME_RE.sub("_", filename).strip("._") or "upload.zip"
        date_path = datetime.now(UTC).strftime("%Y/%m/%d")
        random_suffix = uuid.uuid4().hex
        return f"imports/{user_id}/{mode}/{date_path}/{random_suffix}_{safe_name}"

    def _ensure_not_expired(self, row) -> None:
        if row.expires_at and row.expires_at <= datetime.now(UTC):
            raise BadRequestAppException("upload session expired")

    def _serialize_session(self, row) -> ImportUploadSessionResponse:
        return ImportUploadSessionResponse(
            session_id=row.id,
            mode=row.mode,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            filename=row.filename,
            size=int(row.size or 0),
            uploaded_size=int(row.uploaded_size or 0),
            content_type=row.content_type,
            object_key=row.object_key,
            strategy=ImportUploadStrategy(str(row.strategy)),
            status=ImportUploadSessionStatus(str(row.status)),
            upload_id=row.multipart_upload_id,
            expires_at=row.expires_at,
            error=row.error,
        )

    async def _get_import_max_zip_bytes(self) -> int:
        value = await self.system_settings.get_value(
            SystemSettingKeys.IMPORT_MAX_ZIP_BYTES,
            default=int(settings.IMPORT_MAX_ZIP_BYTES),
        )
        try:
            parsed = int(value)
        except Exception as exc:  # noqa: BLE001
            raise BadRequestAppException(f"invalid import max zip bytes setting: {value}") from exc
        if parsed <= 0:
            raise BadRequestAppException(f"invalid import max zip bytes setting: {parsed}")
        return parsed

    async def _expire_stale_sessions(self) -> None:
        rows = await self.repo.list_expired_active(limit=500)
        if not rows:
            return
        now = datetime.now(UTC)
        for row in rows:
            if row.strategy == ImportUploadStrategy.MULTIPART.value and row.multipart_upload_id:
                try:
                    self.storage.abort_multipart_upload(row.object_key, row.multipart_upload_id)
                except StorageError:
                    pass
            await self._delete_object_if_unreferenced(
                object_key=row.object_key,
                exclude_session_id=row.id,
                now=now,
            )
            row.status = ImportUploadSessionStatus.EXPIRED.value
            row.error = "upload session expired"
            row.completed_at = now
        await self.session.commit()

    async def _delete_object_if_unreferenced(
        self,
        *,
        object_key: str,
        exclude_session_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> None:
        has_live_reference = await self.repo.has_live_object_reference(
            object_key=object_key,
            exclude_session_id=exclude_session_id,
            now=now,
        )
        if has_live_reference:
            return
        try:
            if self.storage.object_exists(object_key):
                self.storage.delete_object(object_key)
        except StorageError:
            pass
