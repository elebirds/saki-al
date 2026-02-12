from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.models  # noqa: F401
from saki_api.api.api_v1.endpoints.l3 import loop_control as loop_control_endpoint
from saki_api.api.api_v1.endpoints.l3 import query as loop_query_endpoint
from saki_api.core.exceptions import BadRequestAppException
from saki_api.db.session import _session_ctx
from saki_api.models.enums import ALLoopMode, ALLoopStatus, AuthorType, JobStatusV2, LoopPhase, TaskType
from saki_api.models.project.branch import Branch
from saki_api.models.project.commit import Commit
from saki_api.models.project.project import Project
from saki_api.models.runtime.job import Job
from saki_api.schemas.runtime.job import (
    LoopCreateRequest,
    LoopRead,
    LoopSimulationConfig,
    LoopUpdateRequest,
    SimulationExperimentCreateRequest,
)
from saki_api.services.runtime.job import JobService


@pytest.fixture
async def loop_api_env(tmp_path):
    db_path = tmp_path / "loop_api_contract_v2.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        yield session_local
    finally:
        await engine.dispose()


async def _seed_project_branch(session: AsyncSession) -> tuple[Project, Branch]:
    project = Project(name="loop-contract-project", task_type=TaskType.DETECTION, config={})
    session.add(project)
    await session.flush()

    init_commit = Commit(
        project_id=project.id,
        parent_id=None,
        message="init",
        author_type=AuthorType.SYSTEM,
        author_id=None,
        stats={},
    )
    session.add(init_commit)
    await session.flush()

    branch = Branch(
        project_id=project.id,
        name="master",
        head_commit_id=init_commit.id,
        description="master",
        is_protected=True,
    )
    session.add(branch)
    await session.commit()
    await session.refresh(project)
    await session.refresh(branch)
    return project, branch


@pytest.mark.anyio
async def test_loop_read_model_validate_accepts_orm_instance(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = JobService(session)

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-a",
                    branch_id=branch.id,
                    query_strategy="random_baseline",
                    model_arch="yolo_det_v1",
                    model_request_config={"epochs": 12, "batch": 8},
                ),
            )
        finally:
            _session_ctx.reset(token)

        parsed = LoopRead.model_validate(loop)
        assert parsed.id == loop.id
        assert parsed.project_id == project.id
        assert parsed.phase == LoopPhase.AL_BOOTSTRAP


@pytest.mark.anyio
async def test_loop_endpoints_create_list_get_update_contract(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(loop_query_endpoint, "_ensure_project_perm", _allow)

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = JobService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            created = await loop_query_endpoint.create_project_loop(
                project_id=project.id,
                payload=LoopCreateRequest(
                    name="loop-b",
                    branch_id=branch.id,
                    query_strategy="random_baseline",
                    model_arch="yolo_det_v1",
                    global_config={"warm_start": False},
                    model_request_config={"epochs": 24, "batch": 16},
                ),
                job_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert created.model_request_config == {"epochs": 24, "batch": 16}

            listed = await loop_query_endpoint.list_project_loops(
                project_id=project.id,
                job_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert len(listed) == 1
            assert listed[0].id == created.id

            fetched = await loop_query_endpoint.get_loop(
                loop_id=created.id,
                job_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert fetched.id == created.id

            updated = await loop_query_endpoint.update_loop(
                loop_id=created.id,
                payload=LoopUpdateRequest(
                    model_arch="demo_det_v1",
                    query_strategy="uncertainty_1_minus_max_conf",
                    model_request_config={"epochs": 30, "lr": 0.001},
                ),
                job_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert updated.model_arch == "demo_det_v1"
            assert updated.query_strategy == "uncertainty_1_minus_max_conf"
            assert updated.model_request_config == {"epochs": 30, "lr": 0.001}
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_create_loop_rejects_duplicate_branch_binding(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = JobService(session)

        token = _session_ctx.set(session)
        try:
            await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-first",
                    branch_id=branch.id,
                    query_strategy="random_baseline",
                    model_arch="yolo_det_v1",
                ),
            )
            with pytest.raises(BadRequestAppException):
                await service.create_loop(
                    project.id,
                    LoopCreateRequest(
                        name="loop-second",
                        branch_id=branch.id,
                        query_strategy="random_baseline",
                        model_arch="yolo_det_v1",
                    ),
                )
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_loop_control_confirm_for_manual_mode(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    async def _noop_tick_once() -> None:
        return None

    monkeypatch.setattr(loop_control_endpoint, "_ensure_project_perm", _allow)
    monkeypatch.setattr(loop_control_endpoint.loop_orchestrator, "tick_once", _noop_tick_once)

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = JobService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-manual",
                    branch_id=branch.id,
                    mode=ALLoopMode.MANUAL,
                    query_strategy="random_baseline",
                    model_arch="yolo_det_v1",
                    status=ALLoopStatus.RUNNING,
                ),
            )
            loop.phase = LoopPhase.MANUAL_WAIT_CONFIRM
            session.add(loop)
            await session.commit()
            await session.refresh(loop)

            resp = await loop_control_endpoint.confirm_loop(
                loop_id=loop.id,
                job_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert resp.loop_id == loop.id
            assert resp.phase == LoopPhase.MANUAL_FINALIZE
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_simulation_experiment_create_and_comparison_contract(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(loop_query_endpoint, "_ensure_project_perm", _allow)

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = JobService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            created = await loop_query_endpoint.create_simulation_experiment(
                project_id=project.id,
                payload=SimulationExperimentCreateRequest(
                    branch_id=branch.id,
                    experiment_name="sim-exp",
                    model_arch="yolo_det_v1",
                    strategies=["uncertainty_1_minus_max_conf"],
                    simulation_config=LoopSimulationConfig(
                        oracle_commit_id=branch.head_commit_id,
                        seed_ratio=0.1,
                        step_ratio=0.1,
                        max_rounds=3,
                        seeds=[0, 1],
                    ),
                ),
                job_service=service,
                session=session,
                current_user_id=current_user_id,
            )

            # random_baseline + one strategy, each with 2 seeds
            assert len(created.loops) == 4
            assert all(loop.mode == ALLoopMode.SIMULATION for loop in created.loops)

            for loop in created.loops:
                for ridx in [1, 2, 3]:
                    base = 0.5 if loop.query_strategy == "random_baseline" else 0.6
                    session.add(
                        Job(
                            project_id=project.id,
                            loop_id=loop.id,
                            round_index=ridx,
                            mode=ALLoopMode.SIMULATION,
                            summary_status=JobStatusV2.JOB_SUCCEEDED,
                            task_counts={"succeeded": 4},
                            job_type="loop_round",
                            plugin_id=loop.model_arch,
                            query_strategy=loop.query_strategy,
                            params={},
                            resources={},
                            source_commit_id=branch.head_commit_id,
                            final_metrics={"map50": base + ridx * 0.01},
                            final_artifacts={},
                        )
                    )
            await session.commit()

            comparison = await loop_query_endpoint.get_simulation_experiment_comparison(
                group_id=created.experiment_group_id,
                metric_name="map50",
                job_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert comparison.experiment_group_id == created.experiment_group_id
            assert comparison.baseline_strategy == "random_baseline"
            strategy_names = {item.strategy for item in comparison.strategies}
            assert "random_baseline" in strategy_names
            assert "uncertainty_1_minus_max_conf" in strategy_names
            assert "uncertainty_1_minus_max_conf" in comparison.delta_vs_baseline
        finally:
            _session_ctx.reset(token)
