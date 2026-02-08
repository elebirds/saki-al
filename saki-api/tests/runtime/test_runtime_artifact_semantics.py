from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.models  # noqa: F401  # Ensure SQLModel metadata registration.
import saki_api.grpc.runtime_control as runtime_control_module
from saki_api.grpc.runtime_control import RuntimeControlService
from saki_api.grpc_gen import runtime_control_pb2 as pb
from saki_api.models.enums import TrainingJobStatus
from saki_api.models.l3.job import Job
from saki_api.models.l3.job_event import JobEvent
from saki_api.models.l3.job_metric_point import JobMetricPoint
from saki_api.services.job import JobService


@pytest.fixture
async def runtime_artifact_env(tmp_path, monkeypatch):
    db_path = tmp_path / "runtime_artifact_semantics.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    monkeypatch.setattr(runtime_control_module, "SessionLocal", session_local)
    try:
        yield session_local
    finally:
        await engine.dispose()


async def _create_job(session_local: async_sessionmaker[AsyncSession]) -> Job:
    job = Job(
        project_id=uuid.uuid4(),
        loop_id=uuid.uuid4(),
        iteration=1,
        status=TrainingJobStatus.PENDING,
        job_type="train_detection",
        plugin_id="demo_det_v1",
        mode="active_learning",
        query_strategy="uncertainty_1_minus_max_conf",
        params={},
        resources={},
        source_commit_id=uuid.uuid4(),
        artifacts={},
        metrics={},
    )
    async with session_local() as session:
        session.add(job)
        await session.commit()
        await session.refresh(job)
    return job


@pytest.mark.anyio
async def test_persist_job_event_artifact_only_accepts_downloadable_uri(runtime_artifact_env):
    session_local = runtime_artifact_env
    service = RuntimeControlService()
    job = await _create_job(session_local)

    await service._persist_job_event(
        pb.JobEvent(
            request_id="evt-1",
            job_id=str(job.id),
            seq=1,
            ts=1,
            artifact_event=pb.ArtifactEvent(
                artifact=pb.ArtifactItem(
                    kind="weights",
                    name="best.pt",
                    uri="runs/job-1/artifacts/best.pt",
                )
            ),
        )
    )
    await service._persist_job_event(
        pb.JobEvent(
            request_id="evt-2",
            job_id=str(job.id),
            seq=2,
            ts=2,
            artifact_event=pb.ArtifactEvent(
                artifact=pb.ArtifactItem(
                    kind="weights",
                    name="best.pt",
                    uri="s3://bucket/runtime/jobs/job-1/best.pt",
                )
            ),
        )
    )

    async with session_local() as session:
        persisted = await session.get(Job, job.id)
        assert persisted is not None
        assert persisted.artifacts == {
            "best.pt": {
                "kind": "weights",
                "uri": "s3://bucket/runtime/jobs/job-1/best.pt",
                "meta": {},
            }
        }


@pytest.mark.anyio
async def test_persist_job_result_filters_undownloadable_artifacts_and_sets_partial_failed(runtime_artifact_env):
    session_local = runtime_artifact_env
    service = RuntimeControlService()
    job = await _create_job(session_local)

    await service._persist_job_result(
        pb.JobResult(
            request_id="result-1",
            job_id=str(job.id),
            status=pb.PARTIAL_FAILED,
            metrics={"map50": 0.5},
            artifacts=[
                pb.ArtifactItem(kind="weights", name="best.pt", uri="runs/job-1/artifacts/best.pt"),
                pb.ArtifactItem(kind="report", name="report.json", uri="s3://bucket/runtime/jobs/job-1/report.json"),
            ],
            error_message="optional artifact upload failed: confusion_matrix.png",
        )
    )

    async with session_local() as session:
        persisted = await session.get(Job, job.id)
        assert persisted is not None
        assert persisted.status == TrainingJobStatus.PARTIAL_FAILED
        assert persisted.last_error == "optional artifact upload failed: confusion_matrix.png"
        assert persisted.metrics["map50"] == 0.5
        assert persisted.artifacts == {
            "report.json": {
                "kind": "report",
                "uri": "s3://bucket/runtime/jobs/job-1/report.json",
                "meta": {},
            }
        }


@pytest.mark.anyio
async def test_job_service_list_artifacts_filters_local_uri(runtime_artifact_env):
    session_local = runtime_artifact_env
    job = await _create_job(session_local)

    async with session_local() as session:
        persisted = await session.get(Job, job.id)
        assert persisted is not None
        persisted.artifacts = {
            "best.pt": {
                "kind": "weights",
                "uri": "runs/job-1/artifacts/best.pt",
                "meta": {},
            },
            "report.json": {
                "kind": "report",
                "uri": "s3://bucket/runtime/jobs/job-1/report.json",
                "meta": {},
            },
        }
        session.add(persisted)
        await session.commit()

    async with session_local() as session:
        service = JobService(session)
        artifacts = await service.list_artifacts(job.id)
        assert artifacts == [
            {
                "name": "report.json",
                "kind": "report",
                "uri": "s3://bucket/runtime/jobs/job-1/report.json",
                "meta": {},
            }
        ]


@pytest.mark.anyio
async def test_persist_job_event_metric_upsert_with_single_step(runtime_artifact_env):
    session_local = runtime_artifact_env
    service = RuntimeControlService()
    job = await _create_job(session_local)

    await service._persist_job_event(
        pb.JobEvent(
            request_id="metric-evt-1",
            job_id=str(job.id),
            seq=1,
            ts=10,
            metric_event=pb.MetricEvent(
                step=5,
                epoch=1,
                metrics={"loss": 0.9, "map50": 0.3},
            ),
        )
    )
    await service._persist_job_event(
        pb.JobEvent(
            request_id="metric-evt-2",
            job_id=str(job.id),
            seq=2,
            ts=11,
            metric_event=pb.MetricEvent(
                step=5,
                epoch=2,
                metrics={"loss": 0.8},
            ),
        )
    )
    # Duplicate seq should be ignored by dedup logic in persistence layer.
    await service._persist_job_event(
        pb.JobEvent(
            request_id="metric-evt-2-dup",
            job_id=str(job.id),
            seq=2,
            ts=12,
            metric_event=pb.MetricEvent(
                step=5,
                epoch=3,
                metrics={"loss": 0.1},
            ),
        )
    )

    async with session_local() as session:
        persisted = await session.get(Job, job.id)
        assert persisted is not None
        assert persisted.metrics == {"loss": 0.8, "map50": 0.3}

        metric_rows = list(
            (
                await session.exec(
                    select(JobMetricPoint)
                    .where(JobMetricPoint.job_id == job.id)
                    .order_by(JobMetricPoint.metric_name.asc())
                )
            ).all()
        )
        assert len(metric_rows) == 2
        assert metric_rows[0].metric_name == "loss"
        assert metric_rows[0].metric_value == 0.8
        assert metric_rows[0].epoch == 2
        assert metric_rows[0].step == 5
        assert metric_rows[1].metric_name == "map50"
        assert metric_rows[1].metric_value == 0.3
        assert metric_rows[1].epoch == 1
        assert metric_rows[1].step == 5

        event_count = (
            await session.exec(select(JobEvent).where(JobEvent.job_id == job.id))
        ).all()
        assert len(event_count) == 2
