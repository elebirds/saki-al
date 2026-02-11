from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.models  # noqa: F401
import saki_api.grpc.runtime_control as runtime_control_module
from saki_api.grpc.runtime_control import RuntimeControlService
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.models.enums import AnnotationSource, AnnotationType, AuthorType, StorageType, TaskType
from saki_api.models.l1.asset import Asset
from saki_api.models.l1.dataset import Dataset
from saki_api.models.l1.sample import Sample
from saki_api.models.l2.annotation import Annotation
from saki_api.models.l2.camap import CommitAnnotationMap
from saki_api.models.l2.commit import Commit
from saki_api.models.l2.label import Label
from saki_api.models.l2.project import Project, ProjectDataset
from saki_api.models.user import User


class _DummyStorage:
    @staticmethod
    def get_presigned_url(*, object_name: str, expires_delta: timedelta) -> str:  # noqa: ARG004
        return f"https://example.test/download/{object_name}"


@pytest.fixture
async def data_response_env(tmp_path, monkeypatch):
    db_path = tmp_path / "runtime_data_response_v2.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    monkeypatch.setattr(runtime_control_module, "SessionLocal", session_local)

    service = RuntimeControlService()
    service._storage = _DummyStorage()  # noqa: SLF001

    try:
        yield service, session_local
    finally:
        await engine.dispose()


async def _seed_context(session_local: async_sessionmaker[AsyncSession]) -> dict[str, uuid.UUID]:
    async with session_local() as session:
        user = User(
            email=f"runtime-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="hashed",
            full_name="runtime user",
            is_active=True,
        )
        session.add(user)
        await session.flush()

        dataset = Dataset(name=f"dataset-{uuid.uuid4().hex[:6]}", owner_id=user.id)
        project = Project(name=f"project-{uuid.uuid4().hex[:6]}", task_type=TaskType.DETECTION, config={})
        session.add(dataset)
        session.add(project)
        await session.flush()

        session.add(ProjectDataset(project_id=project.id, dataset_id=dataset.id))

        commit = Commit(
            project_id=project.id,
            parent_id=None,
            message="init",
            author_type=AuthorType.SYSTEM,
            author_id=None,
            stats={},
        )
        session.add(commit)
        await session.flush()

        label = Label(project_id=project.id, name="car", color="#ff0000")
        session.add(label)
        await session.flush()

        def _asset(name: str) -> Asset:
            return Asset(
                hash=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
                storage_type=StorageType.S3,
                path=f"runtime/{name}.jpg",
                bucket="test-bucket",
                original_filename=f"{name}.jpg",
                extension=".jpg",
                mime_type="image/jpeg",
                size=123,
                meta_info={"width": 640, "height": 480},
            )

        asset_1 = _asset("sample-1")
        asset_2 = _asset("sample-2")
        session.add(asset_1)
        session.add(asset_2)
        await session.flush()

        sample_1 = Sample(
            dataset_id=dataset.id,
            name="sample-1",
            asset_group={"image_main": str(asset_1.id)},
            primary_asset_id=asset_1.id,
            meta_info={"width": 640, "height": 480},
        )
        sample_2 = Sample(
            dataset_id=dataset.id,
            name="sample-2",
            asset_group={"image_main": str(asset_2.id)},
            primary_asset_id=asset_2.id,
            meta_info={"width": 640, "height": 480},
        )
        session.add(sample_1)
        session.add(sample_2)
        await session.flush()

        ann = Annotation(
            sample_id=sample_1.id,
            label_id=label.id,
            project_id=project.id,
            group_id=uuid.uuid4(),
            lineage_id=uuid.uuid4(),
            type=AnnotationType.RECT,
            source=AnnotationSource.MANUAL,
            data={"x": 1, "y": 2, "width": 10, "height": 12},
            confidence=1.0,
        )
        session.add(ann)
        await session.flush()

        session.add(
            CommitAnnotationMap(
                commit_id=commit.id,
                sample_id=sample_1.id,
                annotation_id=ann.id,
                project_id=project.id,
            )
        )
        await session.commit()

        return {
            "project_id": project.id,
            "commit_id": commit.id,
            "sample_1_id": sample_1.id,
            "sample_2_id": sample_2.id,
            "task_id": uuid.uuid4(),
        }


@pytest.mark.anyio
async def test_data_request_labels_returns_label_items(data_response_env):
    service, session_local = data_response_env
    ctx = await _seed_context(session_local)

    response = await service._handle_data_request(  # noqa: SLF001
        pb.DataRequest(
            request_id="req-labels",
            task_id=str(ctx["task_id"]),
            query_type=pb.LABELS,
            project_id=str(ctx["project_id"]),
            commit_id=str(ctx["commit_id"]),
            limit=100,
        )
    )

    assert response.WhichOneof("payload") == "data_response"
    items = [item for item in response.data_response.items if item.WhichOneof("item") == "label_item"]
    assert items
    assert items[0].label_item.name == "car"


@pytest.mark.anyio
async def test_data_request_unlabeled_samples_excludes_labeled(data_response_env):
    service, session_local = data_response_env
    ctx = await _seed_context(session_local)

    response = await service._handle_data_request(  # noqa: SLF001
        pb.DataRequest(
            request_id="req-unlabeled",
            task_id=str(ctx["task_id"]),
            query_type=pb.UNLABELED_SAMPLES,
            project_id=str(ctx["project_id"]),
            commit_id=str(ctx["commit_id"]),
            limit=100,
        )
    )

    assert response.WhichOneof("payload") == "data_response"
    sample_items = [item.sample_item for item in response.data_response.items if item.WhichOneof("item") == "sample_item"]
    sample_ids = {item.id for item in sample_items}
    assert str(ctx["sample_1_id"]) not in sample_ids
    assert str(ctx["sample_2_id"]) in sample_ids


@pytest.mark.anyio
async def test_data_request_annotations_returns_bbox(data_response_env):
    service, session_local = data_response_env
    ctx = await _seed_context(session_local)

    response = await service._handle_data_request(  # noqa: SLF001
        pb.DataRequest(
            request_id="req-ann",
            task_id=str(ctx["task_id"]),
            query_type=pb.ANNOTATIONS,
            project_id=str(ctx["project_id"]),
            commit_id=str(ctx["commit_id"]),
            limit=100,
        )
    )

    assert response.WhichOneof("payload") == "data_response"
    anns = [item.annotation_item for item in response.data_response.items if item.WhichOneof("item") == "annotation_item"]
    assert len(anns) == 1
    assert anns[0].bbox_xywh == [1.0, 2.0, 10.0, 12.0]


@pytest.mark.anyio
async def test_data_request_missing_task_id_returns_error(data_response_env):
    service, session_local = data_response_env
    ctx = await _seed_context(session_local)

    response = await service._handle_data_request(  # noqa: SLF001
        pb.DataRequest(
            request_id="req-bad",
            task_id="",
            query_type=pb.SAMPLES,
            project_id=str(ctx["project_id"]),
            commit_id=str(ctx["commit_id"]),
            limit=10,
        )
    )

    assert response.WhichOneof("payload") == "error"
    assert response.error.code == "invalid_data_request"
