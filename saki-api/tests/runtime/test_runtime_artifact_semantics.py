from __future__ import annotations

import uuid

import pytest
from google.protobuf.struct_pb2 import Struct
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.models  # noqa: F401
import saki_api.grpc.runtime_control as runtime_control_module
from saki_api.grpc.runtime_control import RuntimeControlService
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.models.enums import ALLoopMode, ALLoopStatus, AuthorType, JobStatusV2, JobTaskStatus, JobTaskType, LoopPhase, StorageType, TaskType
from saki_api.models.storage.asset import Asset
from saki_api.models.storage.dataset import Dataset
from saki_api.models.storage.sample import Sample
from saki_api.models.project.branch import Branch
from saki_api.models.project.commit import Commit
from saki_api.models.project.project import Project, ProjectDataset
from saki_api.models.runtime.job import Job
from saki_api.models.runtime.job_task import JobTask
from saki_api.models.runtime.loop import ALLoop
from saki_api.models.runtime.task_candidate_item import TaskCandidateItem
from saki_api.models.runtime.task_event import TaskEvent
from saki_api.models.access.user import User


@pytest.fixture
async def artifact_env(tmp_path, monkeypatch):
    db_path = tmp_path / "runtime_artifact_v2.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    monkeypatch.setattr(runtime_control_module, "SessionLocal", session_local)
    service = RuntimeControlService()

    async with session_local() as session:
        user = User(
            email=f"artifact-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="hashed",
            full_name="artifact user",
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

        branch = Branch(
            project_id=project.id,
            name=f"main-{uuid.uuid4().hex[:6]}",
            head_commit_id=commit.id,
            description="main",
            is_protected=True,
        )
        session.add(branch)
        await session.flush()

        loop = ALLoop(
            project_id=project.id,
            branch_id=branch.id,
            name="loop-a",
            mode=ALLoopMode.ACTIVE_LEARNING,
            phase=LoopPhase.AL_TRAIN,
            phase_meta={},
            query_strategy="random_baseline",
            model_arch="demo_det_v1",
            global_config={},
            current_iteration=1,
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
            round_index=1,
            mode=ALLoopMode.ACTIVE_LEARNING,
            summary_status=JobStatusV2.JOB_PENDING,
            task_counts={},
            job_type="loop_round",
            plugin_id="demo_det_v1",
            query_strategy="random_baseline",
            params={"epochs": 1},
            resources={"gpu_count": 0},
            source_commit_id=commit.id,
            final_metrics={},
            final_artifacts={},
        )
        session.add(job)
        await session.flush()

        task = JobTask(
            job_id=job.id,
            task_type=JobTaskType.SELECT,
            status=JobTaskStatus.RUNNING,
            round_index=1,
            task_index=1,
            depends_on=[],
            params={},
            metrics={},
            artifacts={},
            source_commit_id=commit.id,
            attempt=1,
            max_attempts=3,
        )
        session.add(task)
        await session.flush()

        asset = Asset(
            hash=f"{uuid.uuid4().hex}{uuid.uuid4().hex}",
            storage_type=StorageType.S3,
            path="runtime/sample.jpg",
            bucket="test-bucket",
            original_filename="sample.jpg",
            extension=".jpg",
            mime_type="image/jpeg",
            size=123,
            meta_info={},
        )
        session.add(asset)
        await session.flush()

        sample = Sample(
            dataset_id=dataset.id,
            name="sample-1",
            asset_group={"image_main": str(asset.id)},
            primary_asset_id=asset.id,
            meta_info={},
        )
        session.add(sample)
        await session.commit()

    try:
        yield service, session_local, task.id, job.id, sample.id
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_task_artifact_event_persists_to_task_and_event_table(artifact_env):
    service, session_local, task_id, _job_id, _sample_id = artifact_env

    meta = Struct()
    meta.update({"size": 12})
    message = pb.TaskEvent(
        request_id="evt-1",
        task_id=str(task_id),
        seq=1,
        ts=1000,
        artifact_event=pb.ArtifactEvent(
            artifact=pb.ArtifactItem(
                kind="weights",
                name="best.pt",
                uri="s3://bucket/path/best.pt",
                meta=meta,
            )
        ),
    )

    await service._persist_task_event(message)  # noqa: SLF001

    async with session_local() as session:
        task = await session.get(JobTask, task_id)
        assert task is not None
        assert "best.pt" in (task.artifacts or {})
        assert task.artifacts["best.pt"]["uri"] == "s3://bucket/path/best.pt"

        events = list((await session.exec(select(TaskEvent).where(TaskEvent.task_id == task_id))).all())
        assert len(events) == 1
        assert events[0].event_type == "artifact"


@pytest.mark.anyio
async def test_task_result_updates_metrics_candidates_and_job_aggregate(artifact_env):
    service, session_local, task_id, job_id, sample_id = artifact_env

    reason = Struct()
    reason.update({"score_source": "entropy"})
    artifact_meta = Struct()
    artifact_meta.update({"size": 2048})

    message = pb.TaskResult(
        request_id="result-1",
        task_id=str(task_id),
        status=pb.SUCCEEDED,
        metrics={"map50": 0.61, "recall": 0.73},
        artifacts=[
            pb.ArtifactItem(
                kind="model",
                name="best.pt",
                uri="s3://bucket/path/best.pt",
                meta=artifact_meta,
            )
        ],
        candidates=[
            pb.QueryCandidate(
                sample_id=str(sample_id),
                score=0.95,
                reason=reason,
            )
        ],
        error_message="",
    )

    await service._persist_task_result(message)  # noqa: SLF001

    async with session_local() as session:
        task = await session.get(JobTask, task_id)
        job = await session.get(Job, job_id)
        assert task is not None
        assert job is not None

        assert task.status == JobTaskStatus.SUCCEEDED
        assert task.metrics["map50"] == pytest.approx(0.61)
        assert "best.pt" in (task.artifacts or {})

        candidates = list((await session.exec(select(TaskCandidateItem).where(TaskCandidateItem.task_id == task_id))).all())
        assert len(candidates) == 1
        assert candidates[0].sample_id == sample_id

        assert job.summary_status == JobStatusV2.JOB_SUCCEEDED
        assert job.final_metrics["map50"] == pytest.approx(0.61)
        assert "best.pt" in (job.final_artifacts or {})
