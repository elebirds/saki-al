from __future__ import annotations

import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from saki_api.core.exceptions import BadRequestAppException, ForbiddenAppException
from saki_api.infra.storage.provider import StorageError, StorageObject
from saki_api.modules.importing.domain import ImportUploadSessionStatus, ImportUploadStrategy
from saki_api.modules.importing.schema import ImportUploadInitRequest
from saki_api.modules.importing.service.import_upload_service import ImportUploadService


class _DummySession:
    def __init__(self) -> None:
        self.commit_count = 0

    async def commit(self) -> None:
        self.commit_count += 1


class _DummyRepo:
    def __init__(
        self,
        reusable: Any | None = None,
        *,
        sessions: dict[uuid.UUID, Any] | None = None,
        expired_rows: list[Any] | None = None,
        has_live_reference: bool = False,
    ) -> None:
        self.reusable = reusable
        self.sessions = sessions or {}
        self.expired_rows = expired_rows or []
        self.has_live_reference = has_live_reference
        self.created_rows: list[SimpleNamespace] = []

    async def find_latest_reusable_uploaded_session(self, **_: Any) -> Any | None:
        return self.reusable

    async def create(self, payload: dict[str, Any]) -> SimpleNamespace:
        row = SimpleNamespace(id=uuid.uuid4(), **payload)
        self.created_rows.append(row)
        return row

    async def list_expired_active(self, *, limit: int = 500) -> list[Any]:
        del limit
        return list(self.expired_rows)

    async def get(self, session_id: uuid.UUID) -> Any | None:
        return self.sessions.get(session_id)

    async def has_live_object_reference(self, **_: Any) -> bool:
        return self.has_live_reference


@dataclass
class _DummyStorage:
    put_url: str = "https://example.com/upload"
    head_size: int = 0
    head_error: Exception | None = None
    object_exists_result: bool = True
    deleted_object_keys: list[str] | None = None

    def __post_init__(self) -> None:
        if self.deleted_object_keys is None:
            self.deleted_object_keys = []

    def head_object(self, object_name: str) -> StorageObject:
        if self.head_error:
            raise self.head_error
        return StorageObject(name=object_name, size=self.head_size)

    def get_presigned_put_url(self, object_name: str, expires_delta):  # noqa: ANN001
        del object_name, expires_delta
        return self.put_url

    def init_multipart_upload(self, object_name: str, content_type: str | None = None) -> str:
        del object_name, content_type
        return "upload-id"

    def object_exists(self, object_name: str) -> bool:
        del object_name
        return self.object_exists_result

    def delete_object(self, object_name: str) -> None:
        assert self.deleted_object_keys is not None
        self.deleted_object_keys.append(object_name)


def _build_service(*, repo: _DummyRepo, storage: _DummyStorage) -> tuple[ImportUploadService, _DummySession]:
    service = object.__new__(ImportUploadService)
    session = _DummySession()
    service.session = session
    service.repo = repo
    service.storage = storage
    return service, session


@pytest.mark.anyio
async def test_init_upload_session_reuse_hit_returns_uploaded(monkeypatch: pytest.MonkeyPatch) -> None:
    reusable = SimpleNamespace(
        id=uuid.uuid4(),
        object_key="imports/reusable.zip",
        bucket="saki-data",
        strategy=ImportUploadStrategy.MULTIPART.value,
    )
    repo = _DummyRepo(reusable=reusable)
    storage = _DummyStorage(head_size=1024)
    service, session = _build_service(repo=repo, storage=storage)

    async def _no_permission_check(**_: Any) -> None:
        return None

    async def _max_zip_bytes() -> int:
        return 2 * 1024 * 1024 * 1024

    monkeypatch.setattr(service, "_ensure_mode_permission", _no_permission_check)
    monkeypatch.setattr(service, "_get_import_max_zip_bytes", _max_zip_bytes)

    payload = ImportUploadInitRequest(
        mode="project_associated",
        resource_type="project",
        resource_id=uuid.uuid4(),
        filename="demo.zip",
        size=1024,
        content_type="application/zip",
        file_sha256="a" * 64,
    )
    response = await service.init_upload_session(user_id=uuid.uuid4(), payload=payload)

    assert response.status == ImportUploadSessionStatus.UPLOADED
    assert response.reuse_hit is True
    assert response.url is None
    assert response.upload_id is None
    assert response.strategy == ImportUploadStrategy.MULTIPART
    assert repo.created_rows[0].object_key == "imports/reusable.zip"
    assert repo.created_rows[0].status == ImportUploadSessionStatus.UPLOADED.value
    assert repo.created_rows[0].file_sha256 == "a" * 64
    assert session.commit_count == 1


@pytest.mark.anyio
async def test_init_upload_session_reuse_fallback_to_new_upload_on_head_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reusable = SimpleNamespace(
        id=uuid.uuid4(),
        object_key="imports/reusable.zip",
        bucket="saki-data",
        strategy=ImportUploadStrategy.SINGLE_PUT.value,
    )
    repo = _DummyRepo(reusable=reusable)
    storage = _DummyStorage(head_error=StorageError("not found"))
    service, _ = _build_service(repo=repo, storage=storage)

    async def _no_permission_check(**_: Any) -> None:
        return None

    async def _max_zip_bytes() -> int:
        return 2 * 1024 * 1024 * 1024

    monkeypatch.setattr(service, "_ensure_mode_permission", _no_permission_check)
    monkeypatch.setattr(service, "_get_import_max_zip_bytes", _max_zip_bytes)
    monkeypatch.setattr(
        ImportUploadService,
        "_build_object_key",
        staticmethod(lambda **_: "imports/new-upload.zip"),
    )

    payload = ImportUploadInitRequest(
        mode="dataset_images",
        resource_type="dataset",
        resource_id=uuid.uuid4(),
        filename="demo.zip",
        size=1024,
        content_type="application/zip",
        file_sha256="b" * 64,
    )
    response = await service.init_upload_session(user_id=uuid.uuid4(), payload=payload)

    assert response.status == ImportUploadSessionStatus.INITIATED
    assert response.reuse_hit is False
    assert response.url == "https://example.com/upload"
    assert repo.created_rows[0].object_key == "imports/new-upload.zip"
    assert repo.created_rows[0].status == ImportUploadSessionStatus.INITIATED.value


@pytest.mark.anyio
async def test_init_upload_session_rejects_invalid_file_sha256(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _DummyRepo()
    storage = _DummyStorage(head_size=1024)
    service, _ = _build_service(repo=repo, storage=storage)

    async def _no_permission_check(**_: Any) -> None:
        return None

    async def _max_zip_bytes() -> int:
        return 2 * 1024 * 1024 * 1024

    monkeypatch.setattr(service, "_ensure_mode_permission", _no_permission_check)
    monkeypatch.setattr(service, "_get_import_max_zip_bytes", _max_zip_bytes)

    payload = ImportUploadInitRequest(
        mode="dataset_images",
        resource_type="dataset",
        resource_id=uuid.uuid4(),
        filename="demo.zip",
        size=1024,
        content_type="application/zip",
        file_sha256="g" * 64,
    )
    with pytest.raises(BadRequestAppException, match="file_sha256 must be 64-char hex string"):
        await service.init_upload_session(user_id=uuid.uuid4(), payload=payload)


@pytest.mark.anyio
async def test_init_upload_session_permission_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _DummyRepo()
    storage = _DummyStorage(head_size=1024)
    service, _ = _build_service(repo=repo, storage=storage)

    async def _deny(**_: Any) -> None:
        raise ForbiddenAppException("Permission denied")

    monkeypatch.setattr(service, "_ensure_mode_permission", _deny)

    payload = ImportUploadInitRequest(
        mode="dataset_images",
        resource_type="dataset",
        resource_id=uuid.uuid4(),
        filename="demo.zip",
        size=1024,
        content_type="application/zip",
        file_sha256="c" * 64,
    )
    with pytest.raises(ForbiddenAppException):
        await service.init_upload_session(user_id=uuid.uuid4(), payload=payload)


@pytest.mark.anyio
async def test_abort_upload_skips_delete_when_object_still_referenced() -> None:
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    row = SimpleNamespace(
        id=session_id,
        user_id=user_id,
        strategy=ImportUploadStrategy.SINGLE_PUT.value,
        multipart_upload_id=None,
        status=ImportUploadSessionStatus.UPLOADED.value,
        object_key="imports/reusable.zip",
    )
    repo = _DummyRepo(
        sessions={session_id: row},
        has_live_reference=True,
    )
    storage = _DummyStorage(head_size=1024)
    service, _ = _build_service(repo=repo, storage=storage)

    response = await service.abort_upload(user_id=user_id, session_id=session_id)

    assert response.status == ImportUploadSessionStatus.ABORTED
    assert storage.deleted_object_keys == []


@pytest.mark.anyio
async def test_expire_stale_session_skips_delete_when_object_still_referenced() -> None:
    expired_row = SimpleNamespace(
        id=uuid.uuid4(),
        strategy=ImportUploadStrategy.SINGLE_PUT.value,
        multipart_upload_id=None,
        object_key="imports/reusable.zip",
        status=ImportUploadSessionStatus.UPLOADED.value,
        error=None,
        completed_at=None,
    )
    repo = _DummyRepo(
        expired_rows=[expired_row],
        has_live_reference=True,
    )
    storage = _DummyStorage(head_size=1024)
    service, session = _build_service(repo=repo, storage=storage)

    await service._expire_stale_sessions()

    assert expired_row.status == ImportUploadSessionStatus.EXPIRED.value
    assert storage.deleted_object_keys == []
    assert session.commit_count == 1
