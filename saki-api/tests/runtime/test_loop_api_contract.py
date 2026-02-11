from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.models  # noqa: F401  # Ensure SQLModel metadata registration.
from saki_api.api.api_v1.endpoints.l3 import query as loop_query_endpoint
from saki_api.api.api_v1.endpoints.l3 import loop_control as loop_control_endpoint
from saki_api.core.exceptions import BadRequestAppException
from saki_api.db.session import _session_ctx
from saki_api.models.enums import AuthorType, TaskType, ALLoopStatus, ALLoopMode, LoopRoundStatus
from saki_api.models.l2.branch import Branch
from saki_api.models.l2.commit import Commit
from saki_api.models.l2.project import Project
from saki_api.models.l3.loop_round import LoopRound
from saki_api.schemas.l3.job import (
    LoopCreateRequest,
    LoopRead,
    LoopUpdateRequest,
    LoopRecoverRequest,
    LoopRecoverOverrides,
    LoopSimulationConfig,
    SimulationExperimentCreateRequest,
)
from saki_api.services.job import JobService


@pytest.fixture
async def loop_api_env(tmp_path):
    db_path = tmp_path / "loop_api_contract.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        yield session_local
    finally:
        await engine.dispose()


async def _seed_project_branch(session: AsyncSession) -> tuple[Project, Branch]:
    project = Project(
        name="loop-contract-project",
        task_type=TaskType.DETECTION,
        config={},
    )
    session.add(project)
    await session.flush()
    await session.refresh(project)

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
    await session.refresh(init_commit)

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
                    query_strategy="aug_iou_disagreement_v1",
                    model_arch="yolo_det_v1",
                    model_request_config={"epochs": 12, "batch": 8},
                ),
            )
        finally:
            _session_ctx.reset(token)

        parsed = LoopRead.model_validate(loop)
        assert parsed.id == loop.id
        assert parsed.project_id == project.id


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
                    query_strategy="aug_iou_disagreement_v1",
                    model_arch="yolo_det_v1",
                    global_config={"warm_start": False},
                    model_request_config={"epochs": 24, "batch": 16},
                ),
                job_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert created.model_request_config == {"epochs": 24, "batch": 16}
            assert created.global_config["warm_start"] is False

            listed = await loop_query_endpoint.list_project_loops(
                project_id=project.id,
                job_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert len(listed) == 1
            assert listed[0].id == created.id
            assert listed[0].model_request_config["epochs"] == 24

            fetched = await loop_query_endpoint.get_loop(
                loop_id=created.id,
                job_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert fetched.id == created.id
            assert fetched.model_request_config["batch"] == 16

            updated = await loop_query_endpoint.update_loop(
                loop_id=created.id,
                payload=LoopUpdateRequest(
                    model_arch="demo_det_v1",
                    query_strategy="random_baseline",
                    model_request_config={"epochs": 30, "lr": 0.001},
                ),
                job_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert updated.model_arch == "demo_det_v1"
            assert updated.query_strategy == "random_baseline"
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
                    query_strategy="aug_iou_disagreement_v1",
                    model_arch="yolo_det_v1",
                ),
            )
            with pytest.raises(BadRequestAppException):
                await service.create_loop(
                    project.id,
                    LoopCreateRequest(
                        name="loop-second",
                        branch_id=branch.id,
                        query_strategy="aug_iou_disagreement_v1",
                        model_arch="yolo_det_v1",
                    ),
                )
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_loop_control_start_failed_defaults_to_recover(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(loop_control_endpoint, "_ensure_project_perm", _allow)

    recover_calls: list[tuple[str, str]] = []

    async def fake_recover_failed_loop(*, loop_id, mode, overrides):
        recover_calls.append((str(loop_id), str(mode)))
        return uuid.uuid4()

    monkeypatch.setattr(loop_control_endpoint.loop_orchestrator, "recover_failed_loop", fake_recover_failed_loop)

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = JobService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-failed",
                    branch_id=branch.id,
                    query_strategy="aug_iou_disagreement_v1",
                    model_arch="yolo_det_v1",
                ),
            )
            loop.status = ALLoopStatus.FAILED
            session.add(loop)
            await session.commit()
            await session.refresh(loop)

            resp = await loop_control_endpoint.start_loop(
                loop_id=loop.id,
                job_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert resp.id == loop.id
            assert recover_calls == [(str(loop.id), "retry_same_params")]
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_loop_control_recover_endpoint_accepts_overrides(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(loop_control_endpoint, "_ensure_project_perm", _allow)
    captured: dict[str, object] = {}

    async def fake_recover_failed_loop(*, loop_id, mode, overrides):
        captured["loop_id"] = str(loop_id)
        captured["mode"] = mode
        captured["overrides"] = overrides
        return uuid.uuid4()

    monkeypatch.setattr(loop_control_endpoint.loop_orchestrator, "recover_failed_loop", fake_recover_failed_loop)

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = JobService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-recover",
                    branch_id=branch.id,
                    query_strategy="aug_iou_disagreement_v1",
                    model_arch="yolo_det_v1",
                ),
            )
            loop.status = ALLoopStatus.FAILED
            session.add(loop)
            await session.commit()
            await session.refresh(loop)

            payload = LoopRecoverRequest(
                mode="rerun_with_overrides",
                overrides=LoopRecoverOverrides(
                    plugin_id="demo_det_v1",
                    query_strategy="random_baseline",
                    params={"epochs": 5},
                    resources={"gpu_count": 0},
                ),
            )
            resp = await loop_control_endpoint.recover_loop(
                loop_id=loop.id,
                payload=payload,
                job_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert resp.id == loop.id
            assert captured["mode"] == "rerun_with_overrides"
            assert captured["overrides"] == {
                "query_strategy": "random_baseline",
                "plugin_id": "demo_det_v1",
                "params": {"epochs": 5},
                "resources": {"gpu_count": 0},
            }
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_simulation_experiment_create_and_curves_contract(loop_api_env, monkeypatch):
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
                    strategies=["uncertainty_1_minus_max_conf", "aug_iou_disagreement_v1"],
                    simulation_config=LoopSimulationConfig(
                        oracle_commit_id=branch.head_commit_id,
                        initial_seed_count=10,
                        query_batch_size=20,
                        max_rounds=3,
                        split_seed=7,
                        random_seed=11,
                        require_fully_labeled=False,
                    ),
                ),
                job_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert created.experiment_group_id is not None
            assert len(created.loops) == 3
            assert created.loops[0].query_strategy == "random_baseline"
            assert all(loop.mode == ALLoopMode.SIMULATION for loop in created.loops)
            assert all(loop.branch_id != branch.id for loop in created.loops)

            first_loop = created.loops[0]
            db_loop = await service.loop_repo.get_by_id_or_raise(first_loop.id)
            loop_branch = await session.get(Branch, first_loop.branch_id)
            assert loop_branch is not None
            assert loop_branch.name.startswith("simulation/sim-exp/")
            session.add(
                LoopRound(
                    loop_id=db_loop.id,
                    round_index=1,
                    source_commit_id=loop_branch.head_commit_id,
                    status=LoopRoundStatus.COMPLETED,
                    metrics={"map50": 0.4, "recall": 0.7},
                    selected_count=20,
                    labeled_count=20,
                )
            )
            await session.commit()

            curves = await loop_query_endpoint.get_simulation_experiment_curves(
                group_id=created.experiment_group_id,
                job_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert curves.experiment_group_id == created.experiment_group_id
            assert len(curves.loops) == 3
            curve = next(item for item in curves.loops if item.loop_id == first_loop.id)
            assert len(curve.points) == 1
            assert curve.points[0].map50 == 0.4
            assert curve.points[0].recall == 0.7
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_simulation_experiment_rejects_demo_plugin(loop_api_env, monkeypatch):
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
            with pytest.raises(BadRequestAppException):
                await loop_query_endpoint.create_simulation_experiment(
                    project_id=project.id,
                    payload=SimulationExperimentCreateRequest(
                        branch_id=branch.id,
                        experiment_name="sim-demo",
                        model_arch="demo_det_v1",
                        strategies=["random_baseline"],
                        simulation_config=LoopSimulationConfig(
                            oracle_commit_id=branch.head_commit_id,
                            initial_seed_count=10,
                            query_batch_size=20,
                            max_rounds=3,
                            split_seed=7,
                            random_seed=11,
                            require_fully_labeled=False,
                        ),
                    ),
                    job_service=service,
                    session=session,
                    current_user_id=current_user_id,
                )
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_simulation_experiment_uses_default_name(loop_api_env, monkeypatch):
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
                    model_arch="yolo_det_v1",
                    strategies=["random_baseline"],
                    simulation_config=LoopSimulationConfig(
                        oracle_commit_id=branch.head_commit_id,
                        initial_seed_count=10,
                        query_batch_size=20,
                        max_rounds=3,
                        split_seed=7,
                        random_seed=11,
                        require_fully_labeled=False,
                    ),
                ),
                job_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert created.loops
            first_loop = created.loops[0]
            assert first_loop.name.startswith("simulation-exp-")
            first_branch = await session.get(Branch, first_loop.branch_id)
            assert first_branch is not None
            assert first_branch.name.startswith("simulation/simulation-exp-")
        finally:
            _session_ctx.reset(token)
