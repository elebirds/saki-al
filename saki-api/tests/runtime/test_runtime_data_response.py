from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.models  # noqa: F401  # Ensure SQLModel metadata registration.
import saki_api.grpc.runtime_control as runtime_control_module
from saki_api.grpc.runtime_control import RuntimeControlService
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.models.enums import (
    ALLoopStatus,
    AnnotationBatchStatus,
    AnnotationSource,
    AnnotationType,
    AuthorType,
    StorageType,
    TaskType,
    TrainingJobStatus,
)
from saki_api.models.l1.asset import Asset
from saki_api.models.l1.dataset import Dataset
from saki_api.models.l1.sample import Sample
from saki_api.models.l2.annotation import Annotation
from saki_api.models.l2.branch import Branch
from saki_api.models.l2.camap import CommitAnnotationMap
from saki_api.models.l2.commit import Commit
from saki_api.models.l2.label import Label
from saki_api.models.l2.project import Project, ProjectDataset
from saki_api.models.l3.annotation_batch import AnnotationBatch, AnnotationBatchItem
from saki_api.models.l3.job import Job
from saki_api.models.l3.loop import ALLoop
from saki_api.models.user import User


class _DummyStorage:
    @staticmethod
    def get_presigned_url(object_name: str) -> str:
        return f"https://example.test/download/{object_name}"


@pytest.fixture
async def data_response_env(tmp_path, monkeypatch):
    db_path = tmp_path / "runtime_data_response.sqlite3"
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


async def _seed_runtime_context(session_local: async_sessionmaker[AsyncSession]) -> dict[str, object]:
    async with session_local() as session:
        user = User(
            email=f"runtime-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="hashed",
            full_name="runtime user",
            is_active=True,
        )
        session.add(user)
        await session.flush()

        dataset = Dataset(
            name=f"dataset-{uuid.uuid4().hex[:6]}",
            owner_id=user.id,
        )
        project = Project(
            name=f"project-{uuid.uuid4().hex[:6]}",
            task_type=TaskType.DETECTION,
            config={},
        )
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

        branch = Branch(
            name="master",
            project_id=project.id,
            head_commit_id=commit.id,
            description="master",
            is_protected=True,
        )
        session.add(branch)
        await session.flush()

        loop = ALLoop(
            project_id=project.id,
            branch_id=branch.id,
            name="loop-a",
            query_strategy="aug_iou_disagreement",
            model_arch="yolo_det_v1",
            global_config={},
            current_iteration=0,
            is_active=True,
            status=ALLoopStatus.RUNNING,
            max_rounds=5,
            query_batch_size=10,
            min_seed_labeled=1,
            min_new_labels_per_round=1,
            stop_patience_rounds=2,
            stop_min_gain=0.001,
            auto_register_model=False,
        )
        session.add(loop)
        await session.flush()

        job = Job(
            project_id=project.id,
            loop_id=loop.id,
            iteration=1,
            status=TrainingJobStatus.PENDING,
            job_type="train_detection",
            plugin_id="yolo_det_v1",
            mode="active_learning",
            query_strategy="aug_iou_disagreement",
            params={},
            resources={"gpu_count": 1, "memory_mb": 0},
            source_commit_id=commit.id,
            round_index=1,
        )
        session.add(job)
        await session.commit()

    return {
        "dataset_id": dataset.id,
        "project_id": project.id,
        "commit_id": commit.id,
        "loop_id": loop.id,
        "job_id": job.id,
    }


async def _create_sample(
    session: AsyncSession,
    *,
    dataset_id: uuid.UUID,
    name: str,
    object_key: str,
    width: int = 640,
    height: int = 480,
) -> Sample:
    asset = Asset(
        hash=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
        storage_type=StorageType.S3,
        path=object_key,
        bucket="test-bucket",
        original_filename=f"{name}.jpg",
        extension=".jpg",
        mime_type="image/jpeg",
        size=123,
        meta_info={"width": width, "height": height},
    )
    session.add(asset)
    await session.flush()

    sample = Sample(
        dataset_id=dataset_id,
        name=name,
        asset_group={"image_main": str(asset.id)},
        primary_asset_id=asset.id,
        meta_info={"name": name},
    )
    session.add(sample)
    await session.flush()
    return sample


@pytest.mark.anyio
async def test_build_data_response_samples_returns_items_for_scalar_dataset_ids(data_response_env):
    service, session_local = data_response_env
    context = await _seed_runtime_context(session_local)

    async with session_local() as session:
        sample = await _create_sample(
            session,
            dataset_id=context["dataset_id"],
            name="sample-a",
            object_key="runtime/sample-a.jpg",
        )
        await session.commit()

    response = await service._build_data_response(  # noqa: SLF001
        pb.DataRequest(
            request_id="samples-scalar-1",
            job_id=str(context["job_id"]),
            query_type=pb.SAMPLES,
            project_id=str(context["project_id"]),
            commit_id="",
            limit=10,
        )
    )

    assert response.WhichOneof("payload") == "data_response"
    items = response.data_response.items
    assert len(items) >= 1
    sample_items = [item.sample_item for item in items if item.WhichOneof("item") == "sample_item"]
    assert len(sample_items) == 1
    assert sample_items[0].id == str(sample.id)
    assert response.data_response.next_cursor == ""


@pytest.mark.anyio
async def test_build_data_response_samples_pagination_next_cursor(data_response_env):
    service, session_local = data_response_env
    context = await _seed_runtime_context(session_local)

    async with session_local() as session:
        await _create_sample(
            session,
            dataset_id=context["dataset_id"],
            name="sample-p1",
            object_key="runtime/sample-p1.jpg",
        )
        await _create_sample(
            session,
            dataset_id=context["dataset_id"],
            name="sample-p2",
            object_key="runtime/sample-p2.jpg",
        )
        await session.commit()

    response = await service._build_data_response(  # noqa: SLF001
        pb.DataRequest(
            request_id="samples-page-1",
            job_id=str(context["job_id"]),
            query_type=pb.SAMPLES,
            project_id=str(context["project_id"]),
            commit_id="",
            limit=1,
        )
    )

    assert response.WhichOneof("payload") == "data_response"
    sample_items = [item for item in response.data_response.items if item.WhichOneof("item") == "sample_item"]
    assert len(sample_items) == 1
    assert response.data_response.next_cursor == "1"


@pytest.mark.anyio
async def test_build_data_response_unlabeled_samples_excludes_annotated_and_open_batch(data_response_env):
    service, session_local = data_response_env
    context = await _seed_runtime_context(session_local)

    async with session_local() as session:
        annotated_sample = await _create_sample(
            session,
            dataset_id=context["dataset_id"],
            name="annotated",
            object_key="runtime/annotated.jpg",
        )
        open_batch_sample = await _create_sample(
            session,
            dataset_id=context["dataset_id"],
            name="open-batch",
            object_key="runtime/open-batch.jpg",
        )
        eligible_sample = await _create_sample(
            session,
            dataset_id=context["dataset_id"],
            name="eligible",
            object_key="runtime/eligible.jpg",
        )

        label = Label(
            project_id=context["project_id"],
            name="car",
            color="#ff0000",
        )
        session.add(label)
        await session.flush()

        annotation = Annotation(
            sample_id=annotated_sample.id,
            label_id=label.id,
            project_id=context["project_id"],
            group_id=uuid.uuid4(),
            lineage_id=uuid.uuid4(),
            type=AnnotationType.RECT,
            source=AnnotationSource.MANUAL,
            data={"x": 1, "y": 2, "width": 10, "height": 12},
            confidence=1.0,
        )
        session.add(annotation)
        await session.flush()

        session.add(
            CommitAnnotationMap(
                commit_id=context["commit_id"],
                sample_id=annotated_sample.id,
                annotation_id=annotation.id,
                project_id=context["project_id"],
            )
        )

        batch = AnnotationBatch(
            project_id=context["project_id"],
            loop_id=context["loop_id"],
            job_id=context["job_id"],
            round_index=1,
            status=AnnotationBatchStatus.OPEN,
            total_count=1,
            annotated_count=0,
            meta={},
        )
        session.add(batch)
        await session.flush()

        session.add(
            AnnotationBatchItem(
                batch_id=batch.id,
                sample_id=open_batch_sample.id,
                rank=1,
                score=0.9,
                reason={},
                prediction_snapshot={},
                is_annotated=False,
            )
        )
        await session.commit()

    response = await service._build_data_response(  # noqa: SLF001
        pb.DataRequest(
            request_id="unlabeled-filter-1",
            job_id=str(context["job_id"]),
            query_type=pb.UNLABELED_SAMPLES,
            project_id=str(context["project_id"]),
            commit_id=str(context["commit_id"]),
            limit=100,
        )
    )

    assert response.WhichOneof("payload") == "data_response"
    returned_ids = {
        item.sample_item.id
        for item in response.data_response.items
        if item.WhichOneof("item") == "sample_item"
    }
    assert returned_ids == {str(eligible_sample.id)}


@pytest.mark.anyio
async def test_build_data_response_annotations_maps_obb_with_sample_size(data_response_env):
    service, session_local = data_response_env
    context = await _seed_runtime_context(session_local)

    async with session_local() as session:
        sample = await _create_sample(
            session,
            dataset_id=context["dataset_id"],
            name="obb-sample",
            object_key="runtime/obb-sample.jpg",
            width=200,
            height=100,
        )

        label = Label(
            project_id=context["project_id"],
            name="truck",
            color="#00ff00",
        )
        session.add(label)
        await session.flush()

        annotation = Annotation(
            sample_id=sample.id,
            label_id=label.id,
            project_id=context["project_id"],
            group_id=uuid.uuid4(),
            lineage_id=uuid.uuid4(),
            type=AnnotationType.OBB,
            source=AnnotationSource.MANUAL,
            data={
                "cx": 0.5,
                "cy": 0.5,
                "w": 0.4,
                "h": 0.2,
                "angle_deg": 15.0,
                "normalized": True,
            },
            confidence=0.9,
        )
        session.add(annotation)
        await session.flush()

        session.add(
            CommitAnnotationMap(
                commit_id=context["commit_id"],
                sample_id=sample.id,
                annotation_id=annotation.id,
                project_id=context["project_id"],
            )
        )
        await session.commit()

    response = await service._build_data_response(  # noqa: SLF001
        pb.DataRequest(
            request_id="annotations-obb-1",
            job_id=str(context["job_id"]),
            query_type=pb.ANNOTATIONS,
            project_id=str(context["project_id"]),
            commit_id=str(context["commit_id"]),
            limit=100,
        )
    )

    assert response.WhichOneof("payload") == "data_response"
    items = [item.annotation_item for item in response.data_response.items if item.WhichOneof("item") == "annotation_item"]
    assert len(items) == 1
    item = items[0]
    assert item.sample_id == str(sample.id)
    assert item.category_id == str(label.id)
    assert pytest.approx(item.bbox_xywh[0], rel=0.0, abs=1e-6) == 60.0
    assert pytest.approx(item.bbox_xywh[1], rel=0.0, abs=1e-6) == 40.0
    assert pytest.approx(item.bbox_xywh[2], rel=0.0, abs=1e-6) == 80.0
    assert pytest.approx(item.bbox_xywh[3], rel=0.0, abs=1e-6) == 20.0
    obb_payload = dict(item.obb)
    assert obb_payload["normalized"] is True
    assert pytest.approx(float(obb_payload["angle_deg"]), rel=0.0, abs=1e-6) == 15.0


def test_extract_scalar_values_handles_scalar_and_tuple():
    scalar_value = uuid.uuid4()
    tuple_value = uuid.uuid4()

    extracted = RuntimeControlService._extract_scalar_values(  # noqa: SLF001
        [scalar_value, (tuple_value,), [scalar_value]]
    )
    assert extracted == [scalar_value, tuple_value, scalar_value]
