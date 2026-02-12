from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.models  # noqa: F401
import saki_api.services.runtime.loop_orchestrator as orchestrator_module
from saki_api.models.enums import (
    ALLoopMode,
    ALLoopStatus,
    AnnotationSource,
    AnnotationType,
    AuthorType,
    JobStatusV2,
    JobTaskStatus,
    JobTaskType,
    LoopPhase,
    TaskType,
)
from saki_api.models.storage.dataset import Dataset
from saki_api.models.storage.sample import Sample
from saki_api.models.annotation.annotation import Annotation
from saki_api.models.project.branch import Branch
from saki_api.models.annotation.camap import CommitAnnotationMap
from saki_api.models.project.commit import Commit
from saki_api.models.project.label import Label
from saki_api.models.project.project import Project, ProjectDataset
from saki_api.models.runtime.job import Job
from saki_api.models.runtime.job_task import JobTask
from saki_api.models.runtime.loop import ALLoop
from saki_api.models.access.user import User
from saki_api.services.runtime.loop_orchestrator import LoopOrchestrator


@pytest.fixture
async def orchestrator_env(tmp_path, monkeypatch):
    db_path = tmp_path / "loop_orchestrator_v2.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    enqueue_calls: list[uuid.UUID] = []
    assign_calls: list[uuid.UUID] = []

    async def fake_enqueue(task_id: uuid.UUID) -> None:
        enqueue_calls.append(task_id)

    async def fake_assign(task_id: uuid.UUID) -> bool:
        assign_calls.append(task_id)
        return True

    async def fake_dispatch_pending() -> None:
        return None

    monkeypatch.setattr(orchestrator_module.runtime_dispatcher, "enqueue_task", fake_enqueue)
    monkeypatch.setattr(orchestrator_module.runtime_dispatcher, "assign_task", fake_assign)
    monkeypatch.setattr(orchestrator_module.runtime_dispatcher, "dispatch_pending_tasks", fake_dispatch_pending)

    orchestrator = LoopOrchestrator(interval_sec=2, session_local=session_local)
    try:
        yield session_local, orchestrator, enqueue_calls, assign_calls
    finally:
        await engine.dispose()


async def _seed_base_graph(
    session_local: async_sessionmaker[AsyncSession],
    *,
    mode: ALLoopMode,
    simulation_total_samples: int = 0,
) -> tuple[ALLoop, Branch, Commit]:
    async with session_local() as session:
        project = Project(name=f"proj-{uuid.uuid4().hex[:8]}", task_type=TaskType.DETECTION, config={})
        session.add(project)
        await session.flush()

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

        global_config = {}
        phase = LoopPhase.AL_BOOTSTRAP
        if mode == ALLoopMode.SIMULATION:
            phase = LoopPhase.SIM_BOOTSTRAP
            global_config["simulation"] = {
                "oracle_commit_id": str(commit.id),
                "seed_ratio": 0.1,
                "step_ratio": 0.2,
                "max_rounds": 10,
                "single_seed": 0,
            }
        elif mode == ALLoopMode.MANUAL:
            phase = LoopPhase.MANUAL_IDLE

        loop = ALLoop(
            project_id=project.id,
            branch_id=branch.id,
            name="loop-a",
            mode=mode,
            phase=phase,
            phase_meta={},
            query_strategy="random_baseline",
            model_arch="demo_det_v1",
            global_config=global_config,
            current_iteration=0,
            status=ALLoopStatus.RUNNING,
            max_rounds=10,
            query_batch_size=10,
            min_seed_labeled=1,
            min_new_labels_per_round=1,
            stop_patience_rounds=2,
            stop_min_gain=0.001,
            auto_register_model=False,
        )
        session.add(loop)

        if simulation_total_samples > 0:
            user = User(
                email=f"u-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="hashed",
                full_name="u",
                is_active=True,
            )
            session.add(user)
            await session.flush()

            dataset = Dataset(name=f"ds-{uuid.uuid4().hex[:6]}", owner_id=user.id)
            session.add(dataset)
            await session.flush()
            session.add(ProjectDataset(project_id=project.id, dataset_id=dataset.id))

            label = Label(project_id=project.id, name="car", color="#ff0000")
            session.add(label)
            await session.flush()

            for idx in range(simulation_total_samples):
                sample = Sample(dataset_id=dataset.id, name=f"s-{idx}", asset_group={}, primary_asset_id=None, meta_info={})
                session.add(sample)
                await session.flush()
                ann = Annotation(
                    sample_id=sample.id,
                    label_id=label.id,
                    project_id=project.id,
                    group_id=uuid.uuid4(),
                    lineage_id=uuid.uuid4(),
                    type=AnnotationType.RECT,
                    source=AnnotationSource.MANUAL,
                    data={"x": 1, "y": 1, "width": 10, "height": 10},
                    confidence=1.0,
                )
                session.add(ann)
                await session.flush()
                session.add(
                    CommitAnnotationMap(
                        commit_id=commit.id,
                        sample_id=sample.id,
                        annotation_id=ann.id,
                        project_id=project.id,
                    )
                )

        await session.commit()
        await session.refresh(loop)
        await session.refresh(branch)
        await session.refresh(commit)
        return loop, branch, commit


@pytest.mark.anyio
async def test_create_next_job_active_learning_creates_task_chain(orchestrator_env):
    session_local, orchestrator, enqueue_calls, _assign_calls = orchestrator_env
    loop, branch, _commit = await _seed_base_graph(session_local, mode=ALLoopMode.ACTIVE_LEARNING)

    async with session_local() as session:
        db_loop = await session.get(ALLoop, loop.id)
        db_branch = await session.get(Branch, branch.id)
        assert db_loop is not None and db_branch is not None

        await orchestrator._create_next_job(session=session, loop=db_loop, branch=db_branch)  # noqa: SLF001
        await session.commit()

        jobs = list((await session.exec(select(Job).where(Job.loop_id == loop.id))).all())
        tasks = list((await session.exec(select(JobTask).where(JobTask.job_id == jobs[0].id).order_by(JobTask.task_index))).all())

        assert len(jobs) == 1
        assert [t.task_type for t in tasks] == [
            JobTaskType.TRAIN,
            JobTaskType.SCORE,
            JobTaskType.SELECT,
            JobTaskType.UPLOAD_ARTIFACT,
        ]
        assert db_loop.phase == LoopPhase.AL_TRAIN
        assert db_loop.last_job_id == jobs[0].id
        assert len(enqueue_calls) == 1


@pytest.mark.anyio
async def test_create_next_job_simulation_calculates_ratio_and_add_count(orchestrator_env):
    session_local, orchestrator, enqueue_calls, _assign_calls = orchestrator_env
    loop, branch, _commit = await _seed_base_graph(
        session_local,
        mode=ALLoopMode.SIMULATION,
        simulation_total_samples=10,
    )

    async with session_local() as session:
        db_loop = await session.get(ALLoop, loop.id)
        db_branch = await session.get(Branch, branch.id)
        assert db_loop is not None and db_branch is not None

        await orchestrator._create_next_job(session=session, loop=db_loop, branch=db_branch)  # noqa: SLF001
        await session.commit()

        jobs = list((await session.exec(select(Job).where(Job.loop_id == loop.id))).all())
        tasks = list((await session.exec(select(JobTask).where(JobTask.job_id == jobs[0].id).order_by(JobTask.task_index))).all())

        assert [t.task_type for t in tasks] == [
            JobTaskType.TRAIN,
            JobTaskType.SCORE,
            JobTaskType.AUTO_LABEL,
            JobTaskType.EVAL,
        ]
        assert db_loop.phase == LoopPhase.SIM_TRAIN
        assert db_loop.phase_meta["total_count"] == 10
        assert db_loop.phase_meta["current_ratio"] == pytest.approx(0.1)
        assert db_loop.phase_meta["selected_count"] == 1
        assert db_loop.phase_meta["add_count"] == 0

        simulation_params = tasks[0].params.get("simulation")
        assert simulation_params["target_ratio"] == pytest.approx(0.1)
        assert simulation_params["add_count"] == 0
        assert len(enqueue_calls) == 1


@pytest.mark.anyio
async def test_create_next_job_manual_switches_to_manual_task_running(orchestrator_env):
    session_local, orchestrator, _enqueue_calls, _assign_calls = orchestrator_env
    loop, branch, _commit = await _seed_base_graph(session_local, mode=ALLoopMode.MANUAL)

    async with session_local() as session:
        db_loop = await session.get(ALLoop, loop.id)
        db_branch = await session.get(Branch, branch.id)
        assert db_loop is not None and db_branch is not None

        await orchestrator._create_next_job(session=session, loop=db_loop, branch=db_branch)  # noqa: SLF001
        await session.commit()

        assert db_loop.phase == LoopPhase.MANUAL_TASK_RUNNING


@pytest.mark.anyio
async def test_refresh_job_aggregate_status_from_task_states(orchestrator_env):
    session_local, orchestrator, _enqueue_calls, _assign_calls = orchestrator_env
    loop, branch, commit = await _seed_base_graph(session_local, mode=ALLoopMode.ACTIVE_LEARNING)

    async with session_local() as session:
        job = Job(
            project_id=loop.project_id,
            loop_id=loop.id,
            round_index=1,
            mode=ALLoopMode.ACTIVE_LEARNING,
            summary_status=JobStatusV2.JOB_PENDING,
            task_counts={},
            job_type="loop_round",
            plugin_id="demo_det_v1",
            query_strategy="random_baseline",
            params={},
            resources={},
            source_commit_id=commit.id,
            final_metrics={},
            final_artifacts={},
        )
        session.add(job)
        await session.flush()

        task_ok = JobTask(
            job_id=job.id,
            task_type=JobTaskType.TRAIN,
            status=JobTaskStatus.SUCCEEDED,
            round_index=1,
            task_index=1,
            depends_on=[],
            params={},
            metrics={"map50": 0.5},
            artifacts={},
            source_commit_id=branch.head_commit_id,
            attempt=1,
            max_attempts=2,
        )
        task_fail = JobTask(
            job_id=job.id,
            task_type=JobTaskType.SCORE,
            status=JobTaskStatus.FAILED,
            round_index=1,
            task_index=2,
            depends_on=[str(task_ok.id) if task_ok.id else ""],
            params={},
            metrics={},
            artifacts={},
            source_commit_id=branch.head_commit_id,
            attempt=1,
            max_attempts=2,
            last_error="score failed",
        )
        session.add(task_ok)
        await session.flush()
        task_fail.depends_on = [str(task_ok.id)]
        session.add(task_fail)
        await session.flush()

        await orchestrator._refresh_job_aggregate_status(session=session, job=job)  # noqa: SLF001
        await session.commit()

        await session.refresh(job)
        assert job.summary_status == JobStatusV2.JOB_PARTIAL_FAILED
        assert job.task_counts[JobTaskStatus.SUCCEEDED.value] == 1
        assert job.task_counts[JobTaskStatus.FAILED.value] == 1
