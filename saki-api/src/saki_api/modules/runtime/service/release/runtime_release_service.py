from __future__ import annotations

import io
import tarfile
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import yaml
from fastapi import UploadFile
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import BadRequestAppException, ConflictAppException, NotFoundAppException
from saki_api.modules.runtime.api.runtime_executor import (
    RuntimeDesiredStateItem,
    RuntimeDesiredStatePatchItem,
    RuntimeDesiredStateResponse,
    RuntimeReleaseListResponse,
    RuntimeReleaseRead,
    RuntimeUpdateAttemptListResponse,
    RuntimeUpdateAttemptRead,
)
from saki_api.modules.runtime.domain.runtime_desired_state import RuntimeDesiredState
from saki_api.modules.runtime.domain.runtime_release import RuntimeRelease
from saki_api.modules.runtime.domain.runtime_update_attempt import RuntimeUpdateAttempt
from saki_api.modules.runtime.repo.runtime_desired_state import RuntimeDesiredStateRepository
from saki_api.modules.runtime.repo.runtime_release import RuntimeReleaseRepository
from saki_api.modules.runtime.repo.runtime_update_attempt import RuntimeUpdateAttemptRepository
from saki_api.modules.storage.service.asset import AssetService


@dataclass(slots=True)
class _ValidatedReleaseArchive:
    component_type: str
    component_name: str
    version: str
    sha256: str
    size_bytes: int
    manifest_json: dict[str, Any]


class RuntimeReleaseService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.asset_service = AssetService(session=session)
        self.runtime_release_repo = RuntimeReleaseRepository(session)
        self.runtime_desired_state_repo = RuntimeDesiredStateRepository(session)
        self.runtime_update_attempt_repo = RuntimeUpdateAttemptRepository(session)

    @staticmethod
    def _normalize_archive_entries(names: list[str]) -> set[str]:
        normalized = [str(PurePosixPath(name)) for name in names if str(name or "").strip()]
        top_levels = {
            PurePosixPath(name).parts[0]
            for name in normalized
            if PurePosixPath(name).parts
        }
        strip_prefix = len(top_levels) == 1
        normalized_set: set[str] = set()
        for name in normalized:
            path = PurePosixPath(name)
            if strip_prefix and len(path.parts) > 1:
                path = PurePosixPath(*path.parts[1:])
            normalized_set.add(str(path))
        return normalized_set

    @classmethod
    def _require_archive_entries(
        cls,
        *,
        normalized_entries: set[str],
        required_entries: list[str],
    ) -> None:
        missing: list[str] = []
        for entry in required_entries:
            if entry.endswith("/"):
                if any(item == entry[:-1] or item.startswith(entry) for item in normalized_entries):
                    continue
                missing.append(entry)
                continue
            if entry not in normalized_entries:
                missing.append(entry)
        if missing:
            raise BadRequestAppException(f"发布包缺少必需内容: {', '.join(missing)}")

    @classmethod
    def _read_archive_file(cls, archive: tarfile.TarFile, target: str) -> bytes:
        top_levels = {
            PurePosixPath(name).parts[0]
            for name in archive.getnames()
            if PurePosixPath(name).parts
        }
        single_prefix = next(iter(top_levels)) if len(top_levels) == 1 else None
        candidates = [target]
        if single_prefix:
            candidates.append(str(PurePosixPath(single_prefix) / target))
        for candidate in candidates:
            try:
                member = archive.getmember(candidate)
            except KeyError:
                continue
            file_obj = archive.extractfile(member)
            if file_obj is None:
                continue
            return file_obj.read()
        raise BadRequestAppException(f"发布包缺少文件: {target}")

    @classmethod
    def _validate_release_archive(cls, file: UploadFile) -> _ValidatedReleaseArchive:
        raw_name = str(file.filename or "")
        if not raw_name.endswith(".tar.gz"):
            raise BadRequestAppException("发布包必须是 tar.gz")
        file.file.seek(0)
        raw_bytes = file.file.read()
        file.file.seek(0)
        if not raw_bytes:
            raise BadRequestAppException("发布包为空")
        try:
            with tarfile.open(fileobj=io.BytesIO(raw_bytes), mode="r:gz") as archive:
                names = archive.getnames()
                normalized_entries = cls._normalize_archive_entries(names)
                if "plugin.yml" in normalized_entries:
                    cls._require_archive_entries(
                        normalized_entries=normalized_entries,
                        required_entries=["plugin.yml", "pyproject.toml", "uv.lock", "src/"],
                    )
                    manifest_raw = cls._read_archive_file(archive, "plugin.yml")
                    manifest = yaml.safe_load(manifest_raw.decode("utf-8"))
                    if not isinstance(manifest, dict):
                        raise BadRequestAppException("plugin.yml 格式非法")
                    plugin_id = str(manifest.get("plugin_id") or "").strip()
                    version = str(manifest.get("version") or "").strip()
                    if not plugin_id or not version:
                        raise BadRequestAppException("plugin.yml 必须包含 plugin_id 与 version")
                    return _ValidatedReleaseArchive(
                        component_type="plugin",
                        component_name=plugin_id,
                        version=version,
                        sha256="",
                        size_bytes=len(raw_bytes),
                        manifest_json=manifest,
                    )

                cls._require_archive_entries(
                    normalized_entries=normalized_entries,
                    required_entries=["pyproject.toml", "uv.lock", "src/"],
                )
                pyproject_raw = cls._read_archive_file(archive, "pyproject.toml")
                pyproject = tomllib.loads(pyproject_raw.decode("utf-8"))
                project_payload = pyproject.get("project") if isinstance(pyproject, dict) else None
                if not isinstance(project_payload, dict):
                    raise BadRequestAppException("pyproject.toml 缺少 [project]")
                name = str(project_payload.get("name") or "").strip()
                version = str(project_payload.get("version") or "").strip()
                if not name or not version:
                    raise BadRequestAppException("pyproject.toml 必须包含 project.name 与 project.version")
                component_name = "executor" if name == "saki-executor" else name
                return _ValidatedReleaseArchive(
                    component_type="executor",
                    component_name=component_name,
                    version=version,
                    sha256="",
                    size_bytes=len(raw_bytes),
                    manifest_json={
                        "pyproject": pyproject,
                    },
                )
        except tarfile.TarError as exc:
            raise BadRequestAppException(f"发布包解析失败: {exc}") from exc

    @staticmethod
    def _to_release_read(release: RuntimeRelease) -> RuntimeReleaseRead:
        return RuntimeReleaseRead.model_validate(release)

    @staticmethod
    def _to_attempt_read(attempt: RuntimeUpdateAttempt) -> RuntimeUpdateAttemptRead:
        return RuntimeUpdateAttemptRead.model_validate(attempt)

    async def create_release(self, *, file: UploadFile, current_user_id: uuid.UUID | None) -> RuntimeReleaseRead:
        validated = self._validate_release_archive(file)
        existing = await self.runtime_release_repo.get_by_component_version(
            component_type=validated.component_type,
            component_name=validated.component_name,
            version=validated.version,
        )
        if existing:
            raise ConflictAppException(
                f"发布版本已存在: {validated.component_type}/{validated.component_name}@{validated.version}"
            )

        asset = await self.asset_service.upload_file(file)
        release = await self.runtime_release_repo.create(
            {
                "component_type": validated.component_type,
                "component_name": validated.component_name,
                "version": validated.version,
                "asset_id": asset.id,
                "sha256": asset.hash,
                "size_bytes": int(asset.size or validated.size_bytes),
                "format": "tar.gz",
                "manifest_json": validated.manifest_json,
                "created_by": current_user_id,
            }
        )
        return self._to_release_read(release)

    async def list_releases(
        self,
        *,
        component_type: str | None = None,
        component_name: str | None = None,
    ) -> RuntimeReleaseListResponse:
        filters = []
        if component_type:
            filters.append(RuntimeRelease.component_type == component_type)
        if component_name:
            filters.append(RuntimeRelease.component_name == component_name)
        rows = await self.runtime_release_repo.list(
            filters=filters,
            order_by=[RuntimeRelease.created_at.desc(), RuntimeRelease.component_name.asc()],
        )
        return RuntimeReleaseListResponse(items=[self._to_release_read(item) for item in rows])

    async def list_desired_state(self) -> RuntimeDesiredStateResponse:
        stmt = (
            select(RuntimeDesiredState, RuntimeRelease)
            .join(RuntimeRelease, RuntimeDesiredState.release_id == RuntimeRelease.id)
            .order_by(RuntimeDesiredState.component_type.asc(), RuntimeDesiredState.component_name.asc())
        )
        rows = await self.session.exec(stmt)
        items = [
            RuntimeDesiredStateItem(
                component_type=desired.component_type,
                component_name=desired.component_name,
                release=self._to_release_read(release),
            )
            for desired, release in rows.all()
        ]
        return RuntimeDesiredStateResponse(items=items)

    async def set_desired_state(
        self,
        *,
        items: list[RuntimeDesiredStatePatchItem],
        current_user_id: uuid.UUID | None,
    ) -> RuntimeDesiredStateResponse:
        for item in items:
            component_type = str(item.component_type or "").strip()
            component_name = str(item.component_name or "").strip()
            if not component_type or not component_name:
                raise BadRequestAppException("desired state 必须包含 component_type 与 component_name")
            existing = await self.runtime_desired_state_repo.get_by_component(
                component_type=component_type,
                component_name=component_name,
            )
            if item.release_id is None:
                if existing is not None:
                    await self.session.delete(existing)
                continue

            release = await self.runtime_release_repo.get_by_id(item.release_id)
            if release is None:
                raise NotFoundAppException(f"未找到发布版本: {item.release_id}")
            if release.component_type != component_type or release.component_name != component_name:
                raise BadRequestAppException(
                    f"release 与目标组件不匹配: {component_type}/{component_name} <- {release.component_type}/{release.component_name}"
                )
            if existing is None:
                self.session.add(
                    RuntimeDesiredState(
                        component_type=component_type,
                        component_name=component_name,
                        release_id=release.id,
                        updated_by=current_user_id,
                    )
                )
            else:
                existing.release_id = release.id
                existing.updated_by = current_user_id
                self.session.add(existing)
        await self.session.flush()
        return await self.list_desired_state()

    async def list_update_attempts(
        self,
        *,
        executor_id: str | None = None,
        component_type: str | None = None,
        component_name: str | None = None,
        limit: int = 200,
    ) -> RuntimeUpdateAttemptListResponse:
        limit = max(1, min(limit, 1000))
        stmt = select(RuntimeUpdateAttempt)
        if executor_id:
            stmt = stmt.where(RuntimeUpdateAttempt.executor_id == executor_id)
        if component_type:
            stmt = stmt.where(RuntimeUpdateAttempt.component_type == component_type)
        if component_name:
            stmt = stmt.where(RuntimeUpdateAttempt.component_name == component_name)
        stmt = stmt.order_by(RuntimeUpdateAttempt.started_at.desc(), RuntimeUpdateAttempt.created_at.desc()).limit(limit)
        rows = await self.session.exec(stmt)
        return RuntimeUpdateAttemptListResponse(items=[self._to_attempt_read(item) for item in rows.all()])

    async def get_release_by_id_or_raise(self, release_id: uuid.UUID) -> RuntimeRelease:
        release = await self.runtime_release_repo.get_by_id(release_id)
        if release is None:
            raise NotFoundAppException(f"未找到发布版本: {release_id}")
        return release

    async def remove_desired_state(self, *, component_type: str, component_name: str) -> None:
        stmt = delete(RuntimeDesiredState).where(
            RuntimeDesiredState.component_type == component_type,
            RuntimeDesiredState.component_name == component_name,
        )
        await self.session.exec(stmt)
