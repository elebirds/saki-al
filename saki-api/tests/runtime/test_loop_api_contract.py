from __future__ import annotations

from datetime import UTC, datetime
import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.modules.shared.modeling  # noqa: F401
from saki_api.modules.access.domain.rbac.audit_log import AuditLog
from saki_api.modules.runtime.api.http import query as loop_query_endpoint
from saki_api.modules.runtime.api.http.endpoints import (
    loop_action_endpoints,
    prediction_endpoints,
    snapshot_endpoints,
)
from saki_api.modules.runtime.api.http.endpoints import round_step_query_endpoints as round_step_query_endpoint
from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.infra.db.session import _session_ctx
from saki_api.modules.shared.modeling.enums import (
    AuthorType,
    CommitSampleReviewState,
    LoopActionKey,
    LoopMode,
    LoopPhase,
    LoopGate,
    LoopLifecycle,
    RoundStatus,
    StepDispatchKind,
    StepStatus,
    StepType,
    TaskType,
    RuntimeTaskKind,
    RuntimeTaskStatus,
    RuntimeTaskType,
)
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.project.domain.commit import Commit
from saki_api.modules.project.domain.commit_sample_state import CommitSampleState
from saki_api.modules.project.domain.project import Project, ProjectDataset
from saki_api.modules.runtime.domain.al_snapshot_sample import ALSnapshotSample
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.task import Task
from saki_api.modules.runtime.domain.task_event import TaskEvent
from saki_api.modules.runtime.domain.task_metric_point import TaskMetricPoint
from saki_api.modules.runtime.domain.al_snapshot_version import ALSnapshotVersion
from saki_api.modules.storage.domain.dataset import Dataset
from saki_api.modules.storage.domain.sample import Sample
from saki_api.modules.access.domain.access.user import User
from saki_api.modules.runtime.api.round_step import (
    LoopActionRequest,
    LoopCreateRequest,
    LoopUpdateRequest,
)
from saki_api.modules.runtime.service.runtime_service.snapshot_policy_mixin import SnapshotPolicyMixin
from saki_api.modules.runtime.service.runtime_service import RuntimeService


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


async def _seed_additional_branch(session: AsyncSession, *, project: Project, name: str) -> Branch:
    head_commit = (
        await session.exec(
            select(Commit)
            .where(Commit.project_id == project.id)
            .order_by(Commit.created_at.desc())
            .limit(1)
        )
    ).first()
    if head_commit is None:
        raise RuntimeError("project has no commit")
    branch = Branch(
        project_id=project.id,
        name=name,
        head_commit_id=head_commit.id,
        description=name,
        is_protected=False,
    )
    session.add(branch)
    await session.commit()
    await session.refresh(branch)
    return branch


async def _seed_project_samples(session: AsyncSession, *, project: Project, count: int = 3) -> list[uuid.UUID]:
    user = User(
        email=f"seed-{uuid.uuid4().hex[:8]}@example.com",
        full_name="seed-user",
        hashed_password="hashed",
    )
    session.add(user)
    await session.flush()

    dataset = Dataset(
        owner_id=user.id,
        name=f"dataset-{uuid.uuid4().hex[:6]}",
    )
    session.add(dataset)
    await session.flush()

    session.add(ProjectDataset(project_id=project.id, dataset_id=dataset.id))
    await session.flush()

    sample_ids: list[uuid.UUID] = []
    for idx in range(max(1, int(count))):
        sample = Sample(
            dataset_id=dataset.id,
            name=f"sample-{idx}",
            asset_group={},
        )
        session.add(sample)
        await session.flush()
        sample_ids.append(sample.id)
    await session.commit()
    return sample_ids


async def _create_project_commit(
    session: AsyncSession,
    *,
    project: Project,
    parent_id: uuid.UUID | None,
    message: str = "next",
) -> Commit:
    commit = Commit(
        project_id=project.id,
        parent_id=parent_id,
        message=message,
        author_type=AuthorType.SYSTEM,
        author_id=None,
        stats={},
    )
    session.add(commit)
    await session.commit()
    await session.refresh(commit)
    return commit


async def _set_commit_sample_states(
    session: AsyncSession,
    *,
    project: Project,
    commit_id: uuid.UUID,
    labeled_ids: list[uuid.UUID],
    empty_confirmed_ids: list[uuid.UUID] | None = None,
) -> None:
    rows = [
        CommitSampleState(
            commit_id=commit_id,
            sample_id=sample_id,
            project_id=project.id,
            state=CommitSampleReviewState.LABELED,
        )
        for sample_id in labeled_ids
    ]
    rows.extend(
        [
            CommitSampleState(
                commit_id=commit_id,
                sample_id=sample_id,
                project_id=project.id,
                state=CommitSampleReviewState.EMPTY_CONFIRMED,
            )
            for sample_id in (empty_confirmed_ids or [])
        ]
    )
    session.add_all(rows)
    await session.commit()


def _loop_config(config: dict) -> dict:
    merged = dict(config)
    reproducibility_raw = merged.get("reproducibility")
    reproducibility = dict(reproducibility_raw) if isinstance(reproducibility_raw, dict) else {}
    reproducibility.setdefault("global_seed", "test-global-seed")
    merged["reproducibility"] = reproducibility
    return merged


async def _attach_step_task(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    step: Step,
    plugin_id: str,
) -> Task:
    task = Task(
        project_id=project_id,
        kind=RuntimeTaskKind.STEP,
        task_type=RuntimeTaskType(step.step_type.value),
        status=RuntimeTaskStatus(step.state.value),
        plugin_id=plugin_id,
        input_commit_id=step.input_commit_id,
        resolved_params=dict(step.resolved_params or {}),
        attempt=max(1, int(step.attempt or 1)),
        max_attempts=max(1, int(step.max_attempts or 1)),
    )
    session.add(task)
    await session.flush()
    step.task_id = task.id
    session.add(step)
    await session.flush()
    return task


async def _attach_step_task_with_result_metrics(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    step: Step,
    plugin_id: str,
    result_metrics: dict[str, float] | None = None,
) -> Task:
    task = await _attach_step_task(
        session,
        project_id=project_id,
        step=step,
        plugin_id=plugin_id,
    )
    if isinstance(result_metrics, dict):
        params = dict(task.resolved_params or {})
        params["_result_metrics"] = dict(result_metrics)
        task.resolved_params = params
        session.add(task)
        await session.flush()
    return task


@pytest.mark.anyio
async def test_loop_read_builder_injects_realtime_stage(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-a",
                    branch_id=branch.id,
                    model_arch="yolo_det_v1",
                    config=_loop_config({
                        "plugin": {"epochs": 12, "batch": 8},
                        "sampling": {"strategy": "random_baseline", "topk": 200},
                    }),
                ),
            )
        finally:
            _session_ctx.reset(token)

        parsed = await loop_query_endpoint._build_loop_read(service, loop)
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
        service = RuntimeService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            created = await loop_query_endpoint.create_project_loop(
                project_id=project.id,
                payload=LoopCreateRequest(
                    name="loop-b",
                    branch_id=branch.id,
                    model_arch="yolo_det_v1",
                    config=_loop_config({
                        "plugin": {"epochs": 24, "batch": 16},
                        "sampling": {"strategy": "random_baseline", "topk": 200},
                    }),
                ),
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            plugin_cfg = created.config.get("plugin") or {}
            assert plugin_cfg.get("epochs") == 24
            assert plugin_cfg.get("batch") == 16
            # annotation_types is injected from the project's enabled_annotation_types
            assert isinstance(plugin_cfg.get("annotation_types"), list)
            assert created.config.get("reproducibility", {}).get("deterministic_level") == "off"

            listed = await loop_query_endpoint.list_project_loops(
                project_id=project.id,
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert len(listed) == 1
            assert listed[0].id == created.id

            fetched = await loop_query_endpoint.get_loop(
                loop_id=created.id,
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert fetched.id == created.id

            updated = await loop_query_endpoint.update_loop(
                loop_id=created.id,
                payload=LoopUpdateRequest(
                    model_arch="demo_det_v1",
                    config=_loop_config({
                        "plugin": {"epochs": 30, "lr": 0.001},
                        "sampling": {"strategy": "uncertainty_1_minus_max_conf", "topk": 256},
                    }),
                ),
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert updated.model_arch == "demo_det_v1"
            assert updated.config.get("sampling", {}).get("strategy") == "uncertainty_1_minus_max_conf"
            assert updated.config.get("sampling", {}).get("topk") == 256
            assert updated.config.get("plugin") == {"epochs": 30, "lr": 0.001}
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_create_loop_rejects_duplicate_branch_binding(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)

        token = _session_ctx.set(session)
        try:
            await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-first",
                    branch_id=branch.id,
                    model_arch="yolo_det_v1",
                    config=_loop_config({"sampling": {"strategy": "random_baseline", "topk": 200}}),
                ),
            )
            with pytest.raises(BadRequestAppException):
                await service.create_loop(
                    project.id,
                    LoopCreateRequest(
                        name="loop-second",
                        branch_id=branch.id,
                        model_arch="yolo_det_v1",
                        config=_loop_config({"sampling": {"strategy": "random_baseline", "topk": 200}}),
                    ),
                )
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_create_loop_requires_global_seed(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)

        token = _session_ctx.set(session)
        try:
            with pytest.raises(BadRequestAppException, match="global_seed"):
                await service.create_loop(
                    project.id,
                    LoopCreateRequest(
                        name="loop-no-seed",
                        branch_id=branch.id,
                        model_arch="yolo_det_v1",
                        config={"sampling": {"strategy": "random_baseline", "topk": 200}},
                    ),
                )
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_create_simulation_loop_rejects_oracle_commit_from_other_project(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project_a, branch_a = await _seed_project_branch(session)
        project_b, branch_b = await _seed_project_branch(session)
        service = RuntimeService(session)

        token = _session_ctx.set(session)
        try:
            with pytest.raises(BadRequestAppException, match="same project"):
                await service.create_loop(
                    project_a.id,
                    LoopCreateRequest(
                        name="loop-sim-invalid-oracle",
                        branch_id=branch_a.id,
                        mode=LoopMode.SIMULATION,
                        model_arch="yolo_det_v1",
                        config=_loop_config(
                            {
                                "sampling": {"strategy": "random_baseline", "topk": 200},
                                "mode": {"oracle_commit_id": str(branch_b.head_commit_id)},
                            }
                        ),
                        lifecycle=LoopLifecycle.DRAFT,
                    ),
                )
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_create_simulation_loop_requires_valid_oracle_commit_uuid(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)

        token = _session_ctx.set(session)
        try:
            with pytest.raises(BadRequestAppException, match="valid UUID"):
                await service.create_loop(
                    project.id,
                    LoopCreateRequest(
                        name="loop-sim-invalid-oracle-uuid",
                        branch_id=branch.id,
                        mode=LoopMode.SIMULATION,
                        model_arch="yolo_det_v1",
                        config=_loop_config(
                            {
                                "sampling": {"strategy": "random_baseline", "topk": 200},
                                "mode": {"oracle_commit_id": "not-a-uuid"},
                            }
                        ),
                        lifecycle=LoopLifecycle.DRAFT,
                    ),
                )
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_update_loop_rejects_global_seed_change_after_non_draft(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-seed-locked",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config=_loop_config({"sampling": {"strategy": "random_baseline", "topk": 200}}),
                    lifecycle=LoopLifecycle.RUNNING,
                ),
            )
            with pytest.raises(BadRequestAppException, match="global_seed is immutable"):
                await service.update_loop(
                    loop.id,
                    LoopUpdateRequest(
                        config={
                            "sampling": {"strategy": "random_baseline", "topk": 200},
                            "reproducibility": {"global_seed": "changed-seed"},
                        }
                    ),
                )
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_create_loop_accepts_deterministic_and_strong_deterministic_levels(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)

        token = _session_ctx.set(session)
        try:
            loop_det = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-deterministic",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config=_loop_config(
                        {
                            "sampling": {"strategy": "random_baseline", "topk": 200},
                            "reproducibility": {
                                "global_seed": "seed-deterministic",
                                "deterministic_level": "deterministic",
                            },
                        }
                    ),
                    lifecycle=LoopLifecycle.DRAFT,
                ),
            )
            assert loop_det.config.get("reproducibility", {}).get("deterministic_level") == "deterministic"

            branch_2 = await _seed_additional_branch(session, project=project, name="al-branch-2")
            loop_strong = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-strong-deterministic",
                    branch_id=branch_2.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config=_loop_config(
                        {
                            "sampling": {"strategy": "random_baseline", "topk": 200},
                            "reproducibility": {
                                "global_seed": "seed-strong",
                                "deterministic_level": "strong_deterministic",
                            },
                        }
                    ),
                    lifecycle=LoopLifecycle.DRAFT,
                ),
            )
            assert loop_strong.config.get("reproducibility", {}).get("deterministic_level") == "strong_deterministic"
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_create_loop_rejects_legacy_deterministic_level_values(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)

        token = _session_ctx.set(session)
        try:
            with pytest.raises(BadRequestAppException, match="deterministic_level"):
                await service.create_loop(
                    project.id,
                    LoopCreateRequest(
                        name="loop-invalid-deterministic-level",
                        branch_id=branch.id,
                        mode=LoopMode.ACTIVE_LEARNING,
                        model_arch="yolo_det_v1",
                        config=_loop_config(
                            {
                                "sampling": {"strategy": "random_baseline", "topk": 200},
                                "reproducibility": {
                                    "global_seed": "seed-invalid",
                                    "deterministic_level": "strict",
                                },
                            }
                        ),
                        lifecycle=LoopLifecycle.DRAFT,
                    ),
                )
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_update_loop_rejects_deterministic_level_change_after_non_draft(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-deterministic-level-locked",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config=_loop_config(
                        {
                            "sampling": {"strategy": "random_baseline", "topk": 200},
                            "reproducibility": {
                                "global_seed": "seed-lock",
                                "deterministic_level": "off",
                            },
                        }
                    ),
                    lifecycle=LoopLifecycle.RUNNING,
                ),
            )
            with pytest.raises(BadRequestAppException, match="deterministic_level is immutable"):
                await service.update_loop(
                    loop.id,
                    LoopUpdateRequest(
                        config={
                            "sampling": {"strategy": "random_baseline", "topk": 200},
                            "reproducibility": {
                                "global_seed": "seed-lock",
                                "deterministic_level": "deterministic",
                            },
                        }
                    ),
                )
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_update_loop_oracle_commit_change_requires_draft_and_no_snapshot(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        sample_ids = await _seed_project_samples(session, project=project, count=2)
        next_commit = await _create_project_commit(
            session,
            project=project,
            parent_id=branch.head_commit_id,
            message="oracle-v2",
        )
        await _set_commit_sample_states(
            session,
            project=project,
            commit_id=branch.head_commit_id,
            labeled_ids=[sample_ids[0]],
        )
        await _set_commit_sample_states(
            session,
            project=project,
            commit_id=next_commit.id,
            labeled_ids=[sample_ids[0]],
        )
        service = RuntimeService(session)

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-sim-oracle-change",
                    branch_id=branch.id,
                    mode=LoopMode.SIMULATION,
                    model_arch="yolo_det_v1",
                    config=_loop_config(
                        {
                            "sampling": {"strategy": "random_baseline", "topk": 200},
                            "mode": {"oracle_commit_id": str(branch.head_commit_id)},
                        }
                    ),
                    lifecycle=LoopLifecycle.DRAFT,
                ),
            )

            updated = await service.update_loop(
                loop.id,
                LoopUpdateRequest(
                    config=_loop_config(
                        {
                            "sampling": {"strategy": "random_baseline", "topk": 200},
                            "mode": {"oracle_commit_id": str(next_commit.id)},
                        }
                    )
                ),
            )
            assert updated.config.get("mode", {}).get("oracle_commit_id") == str(next_commit.id)

            await service.init_loop_snapshot(
                loop_id=loop.id,
                payload={"sample_ids": [str(sample_ids[0])]},
                actor_user_id=None,
            )

            with pytest.raises(
                BadRequestAppException,
                match="oracle_commit_id/config.mode.snapshot_init can only change while loop is draft and snapshot is not initialized",
            ):
                await service.update_loop(
                    loop.id,
                    LoopUpdateRequest(
                        config=_loop_config(
                            {
                                "sampling": {"strategy": "random_baseline", "topk": 200},
                                "mode": {"oracle_commit_id": str(branch.head_commit_id)},
                            }
                        )
                    ),
                )
            with pytest.raises(
                BadRequestAppException,
                match="oracle_commit_id/config.mode.snapshot_init can only change while loop is draft and snapshot is not initialized",
            ):
                await service.update_loop(
                    loop.id,
                    LoopUpdateRequest(
                        config=_loop_config(
                            {
                                "sampling": {"strategy": "random_baseline", "topk": 200},
                                "mode": {
                                    "oracle_commit_id": str(next_commit.id),
                                    "snapshot_init": {
                                        "train_seed_ratio": 0.25,
                                        "val_ratio": 0.15,
                                        "test_ratio": 0.2,
                                        "val_policy": "expand_with_batch_val",
                                    },
                                },
                            }
                        )
                    ),
                )
        finally:
            _session_ctx.reset(token)


def test_effective_round_min_required_requires_full_selected():
    assert SnapshotPolicyMixin._effective_round_min_required(selected_count=0, configured_min_required=1) == 0
    assert SnapshotPolicyMixin._effective_round_min_required(selected_count=2, configured_min_required=1) == 2
    assert SnapshotPolicyMixin._effective_round_min_required(selected_count=5, configured_min_required=2) == 5


@pytest.mark.anyio
async def test_snapshot_init_uses_loop_global_seed_when_seed_missing(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        sample_ids = await _seed_project_samples(session, project=project, count=3)
        service = RuntimeService(session)

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-snapshot-init-seed",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config={
                        "sampling": {"strategy": "random_baseline", "topk": 200},
                        "reproducibility": {"global_seed": "seed-loop-main"},
                    },
                    lifecycle=LoopLifecycle.DRAFT,
                ),
            )
            await service.init_loop_snapshot(
                loop_id=loop.id,
                payload={"sample_ids": [str(item) for item in sample_ids]},
                actor_user_id=None,
            )
            rows = list(
                (
                    await session.exec(
                        select(ALSnapshotVersion)
                        .where(ALSnapshotVersion.loop_id == loop.id)
                        .order_by(ALSnapshotVersion.version_index.asc())
                    )
                ).all()
            )
            assert len(rows) == 1
            assert rows[0].seed == "seed-loop-main"
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_snapshot_update_uses_loop_global_seed_when_seed_missing(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        sample_ids = await _seed_project_samples(session, project=project, count=4)
        service = RuntimeService(session)

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-snapshot-update-seed",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config={
                        "sampling": {"strategy": "random_baseline", "topk": 200},
                        "reproducibility": {"global_seed": "seed-loop-main-2"},
                    },
                    lifecycle=LoopLifecycle.DRAFT,
                ),
            )
            await service.init_loop_snapshot(
                loop_id=loop.id,
                payload={"sample_ids": [str(item) for item in sample_ids[:2]]},
                actor_user_id=None,
            )
            await service.update_loop_snapshot(
                loop_id=loop.id,
                payload={
                    "mode": "append_all_to_pool",
                    "sample_ids": [str(item) for item in sample_ids[2:]],
                },
                actor_user_id=None,
            )
            rows = list(
                (
                    await session.exec(
                        select(ALSnapshotVersion)
                        .where(ALSnapshotVersion.loop_id == loop.id)
                        .order_by(ALSnapshotVersion.version_index.asc())
                    )
                ).all()
            )
            assert len(rows) == 2
            assert rows[0].seed == "seed-loop-main-2"
            assert rows[1].seed == "seed-loop-main-2"
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_simulation_snapshot_init_defaults_to_oracle_labeled_subset(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        sample_ids = await _seed_project_samples(session, project=project, count=5)
        await _set_commit_sample_states(
            session,
            project=project,
            commit_id=branch.head_commit_id,
            labeled_ids=[sample_ids[0], sample_ids[3]],
            empty_confirmed_ids=[sample_ids[1]],
        )
        service = RuntimeService(session)

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-sim-snapshot-oracle-default",
                    branch_id=branch.id,
                    mode=LoopMode.SIMULATION,
                    model_arch="yolo_det_v1",
                    config=_loop_config(
                        {
                            "sampling": {"strategy": "random_baseline", "topk": 200},
                            "mode": {"oracle_commit_id": str(branch.head_commit_id)},
                        }
                    ),
                    lifecycle=LoopLifecycle.DRAFT,
                ),
            )
            await service.init_loop_snapshot(loop_id=loop.id, payload={}, actor_user_id=None)
            snapshot = (
                await session.exec(
                    select(ALSnapshotVersion)
                    .where(ALSnapshotVersion.loop_id == loop.id)
                    .order_by(ALSnapshotVersion.version_index.desc())
                )
            ).first()
            assert snapshot is not None
            rows = list(
                (
                    await session.exec(
                        select(ALSnapshotSample).where(ALSnapshotSample.snapshot_version_id == snapshot.id)
                    )
                ).all()
            )
            assert {row.sample_id for row in rows} == {sample_ids[0], sample_ids[1], sample_ids[3]}
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_simulation_snapshot_init_rejects_non_oracle_sample_subset(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        sample_ids = await _seed_project_samples(session, project=project, count=3)
        await _set_commit_sample_states(
            session,
            project=project,
            commit_id=branch.head_commit_id,
            labeled_ids=[sample_ids[0]],
        )
        service = RuntimeService(session)

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-sim-snapshot-oracle-subset-reject",
                    branch_id=branch.id,
                    mode=LoopMode.SIMULATION,
                    model_arch="yolo_det_v1",
                    config=_loop_config(
                        {
                            "sampling": {"strategy": "random_baseline", "topk": 200},
                            "mode": {"oracle_commit_id": str(branch.head_commit_id)},
                        }
                    ),
                    lifecycle=LoopLifecycle.DRAFT,
                ),
            )
            with pytest.raises(BadRequestAppException, match="subset of oracle labeled samples"):
                await service.init_loop_snapshot(
                    loop_id=loop.id,
                    payload={"sample_ids": [str(sample_ids[0]), str(sample_ids[1])]},
                    actor_user_id=None,
                )
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_simulation_snapshot_update_defaults_to_oracle_labeled_delta(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        sample_ids = await _seed_project_samples(session, project=project, count=4)
        await _set_commit_sample_states(
            session,
            project=project,
            commit_id=branch.head_commit_id,
            labeled_ids=[sample_ids[0], sample_ids[1], sample_ids[2]],
        )
        service = RuntimeService(session)

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-sim-snapshot-update-oracle-delta",
                    branch_id=branch.id,
                    mode=LoopMode.SIMULATION,
                    model_arch="yolo_det_v1",
                    config=_loop_config(
                        {
                            "sampling": {"strategy": "random_baseline", "topk": 200},
                            "mode": {"oracle_commit_id": str(branch.head_commit_id)},
                        }
                    ),
                    lifecycle=LoopLifecycle.DRAFT,
                ),
            )
            await service.init_loop_snapshot(
                loop_id=loop.id,
                payload={"sample_ids": [str(sample_ids[0])]},
                actor_user_id=None,
            )
            await service.update_loop_snapshot(
                loop_id=loop.id,
                payload={"mode": "append_all_to_pool"},
                actor_user_id=None,
            )

            snapshot = (
                await session.exec(
                    select(ALSnapshotVersion)
                    .where(ALSnapshotVersion.loop_id == loop.id)
                    .order_by(ALSnapshotVersion.version_index.desc())
                )
            ).first()
            assert snapshot is not None
            rows = list(
                (
                    await session.exec(
                        select(ALSnapshotSample).where(ALSnapshotSample.snapshot_version_id == snapshot.id)
                    )
                ).all()
            )
            assert {row.sample_id for row in rows} == {sample_ids[0], sample_ids[1], sample_ids[2]}
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_simulation_snapshot_update_rejects_non_oracle_sample_subset(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        sample_ids = await _seed_project_samples(session, project=project, count=3)
        await _set_commit_sample_states(
            session,
            project=project,
            commit_id=branch.head_commit_id,
            labeled_ids=[sample_ids[0]],
        )
        service = RuntimeService(session)

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-sim-snapshot-update-oracle-subset-reject",
                    branch_id=branch.id,
                    mode=LoopMode.SIMULATION,
                    model_arch="yolo_det_v1",
                    config=_loop_config(
                        {
                            "sampling": {"strategy": "random_baseline", "topk": 200},
                            "mode": {"oracle_commit_id": str(branch.head_commit_id)},
                        }
                    ),
                    lifecycle=LoopLifecycle.DRAFT,
                ),
            )
            await service.init_loop_snapshot(
                loop_id=loop.id,
                payload={"sample_ids": [str(sample_ids[0])]},
                actor_user_id=None,
            )
            with pytest.raises(BadRequestAppException, match="subset of oracle labeled samples"):
                await service.update_loop_snapshot(
                    loop_id=loop.id,
                    payload={"mode": "append_all_to_pool", "sample_ids": [str(sample_ids[1])]},
                    actor_user_id=None,
                )
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_simulation_reveal_source_commit_fixed_to_oracle(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        oracle_commit_id = branch.head_commit_id
        next_commit = await _create_project_commit(
            session,
            project=project,
            parent_id=oracle_commit_id,
            message="head-moved",
        )
        branch.head_commit_id = next_commit.id
        session.add(branch)
        await session.commit()
        await session.refresh(branch)
        service = RuntimeService(session)

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-sim-reveal-source-oracle",
                    branch_id=branch.id,
                    mode=LoopMode.SIMULATION,
                    model_arch="yolo_det_v1",
                    config=_loop_config(
                        {
                            "sampling": {"strategy": "random_baseline", "topk": 200},
                            "mode": {"oracle_commit_id": str(oracle_commit_id)},
                        }
                    ),
                    lifecycle=LoopLifecycle.DRAFT,
                ),
            )
            reveal_commit_id = await service._resolve_reveal_source_commit_id(loop=loop)
            assert reveal_commit_id == oracle_commit_id
            assert reveal_commit_id != branch.head_commit_id
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_loop_stage_snapshot_required_does_not_offer_start_action(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-al-snapshot-required",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config=_loop_config({"sampling": {"strategy": "random_baseline", "topk": 200}}),
                    lifecycle=LoopLifecycle.DRAFT,
                ),
            )
            gate = await service.get_loop_gate(loop_id=loop.id)
            assert gate["gate"] == LoopGate.NEED_SNAPSHOT
            action_keys = {str(item.get("key")) for item in gate.get("actions") or []}
            assert "snapshot_init" in action_keys
            assert "start" not in action_keys
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_simulation_draft_without_snapshot_can_start(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        sample_ids = await _seed_project_samples(session, project=project, count=1)
        await _set_commit_sample_states(
            session,
            project=project,
            commit_id=branch.head_commit_id,
            labeled_ids=[sample_ids[0]],
        )
        service = RuntimeService(session)

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-sim-can-start",
                    branch_id=branch.id,
                    mode=LoopMode.SIMULATION,
                    model_arch="yolo_det_v1",
                    config=_loop_config(
                        {
                            "sampling": {"strategy": "random_baseline", "topk": 200},
                            "mode": {"oracle_commit_id": str(branch.head_commit_id)},
                        }
                    ),
                    lifecycle=LoopLifecycle.DRAFT,
                ),
            )
            gate = await service.get_loop_gate(loop_id=loop.id)
            assert gate["gate"] == LoopGate.CAN_START
            action_keys = {str(item.get("key")) for item in gate.get("actions") or []}
            assert "start" in action_keys
            assert "snapshot_init" not in action_keys
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_loop_control_act_start_bootstraps_simulation_snapshot(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(loop_action_endpoints, "ensure_loop_project_perm", _allow)
    monkeypatch.setattr(prediction_endpoints, "ensure_loop_project_perm", _allow)
    monkeypatch.setattr(snapshot_endpoints, "ensure_loop_project_perm", _allow)

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        sample_ids = await _seed_project_samples(session, project=project, count=3)
        await _set_commit_sample_states(
            session,
            project=project,
            commit_id=branch.head_commit_id,
            labeled_ids=[sample_ids[0], sample_ids[1], sample_ids[2]],
        )
        service = RuntimeService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-sim-start-bootstrap",
                    branch_id=branch.id,
                    mode=LoopMode.SIMULATION,
                    model_arch="yolo_det_v1",
                    config=_loop_config(
                        {
                            "sampling": {"strategy": "random_baseline", "topk": 200},
                            "reproducibility": {"global_seed": "sim-seed-main"},
                            "mode": {
                                "oracle_commit_id": str(branch.head_commit_id),
                                "snapshot_init": {
                                    "train_seed_ratio": 0.2,
                                    "val_ratio": 0.3,
                                    "test_ratio": 0.4,
                                    "val_policy": "anchor_only",
                                },
                            },
                        }
                    ),
                    lifecycle=LoopLifecycle.DRAFT,
                ),
            )

            commit_counter = {"count": 0}
            _orig_commit = session.commit

            async def _commit_spy():
                commit_counter["count"] += 1
                return await _orig_commit()

            monkeypatch.setattr(session, "commit", _commit_spy)

            class _DispatcherAdminStub:
                def __init__(self) -> None:
                    self.enabled = True
                    self.start_calls: list[str] = []

                async def start_loop(self, loop_id: str):
                    assert commit_counter["count"] >= 1
                    self.start_calls.append(loop_id)

                    class _Resp:
                        command_id = "cmd-start"
                        message = "start dispatched"

                    return _Resp()

            dispatcher_admin_stub = _DispatcherAdminStub()

            await loop_action_endpoints.act_loop(
                loop_id=loop.id,
                payload=LoopActionRequest(action=LoopActionKey.START),
                runtime_service=service,
                dispatcher_admin_client=dispatcher_admin_stub,
                session=session,
                current_user_id=current_user_id,
            )
            assert dispatcher_admin_stub.start_calls == [str(loop.id)]

            snapshots = list(
                (
                    await session.exec(
                        select(ALSnapshotVersion)
                        .where(ALSnapshotVersion.loop_id == loop.id)
                        .order_by(ALSnapshotVersion.version_index.asc())
                    )
                ).all()
            )
            assert len(snapshots) == 1
            assert snapshots[0].seed == "sim-seed-main"
            rule_json = dict(snapshots[0].rule_json or {})
            assert float(rule_json.get("train_seed_ratio")) == pytest.approx(0.2)
            assert float(rule_json.get("val_ratio")) == pytest.approx(0.3)
            assert float(rule_json.get("test_ratio")) == pytest.approx(0.4)
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_loop_control_act_confirm_rejects_manual_mode(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(loop_action_endpoints, "ensure_loop_project_perm", _allow)
    monkeypatch.setattr(prediction_endpoints, "ensure_loop_project_perm", _allow)
    monkeypatch.setattr(snapshot_endpoints, "ensure_loop_project_perm", _allow)

    class _DispatcherAdminStub:
        def __init__(self) -> None:
            self.enabled = True
            self.confirm_calls: list[tuple[str, bool]] = []

        async def confirm_loop(self, loop_id: str, force: bool = False):
            self.confirm_calls.append((loop_id, force))

    dispatcher_admin_stub = _DispatcherAdminStub()

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-manual",
                    branch_id=branch.id,
                    mode=LoopMode.MANUAL,
                    model_arch="yolo_det_v1",
                    config=_loop_config({"plugin": {"epochs": 1}}),
                    lifecycle=LoopLifecycle.RUNNING,
                ),
            )
            loop.phase = LoopPhase.MANUAL_EVAL
            session.add(loop)
            await session.commit()
            await session.refresh(loop)

            with pytest.raises(BadRequestAppException):
                await loop_action_endpoints.act_loop(
                    loop_id=loop.id,
                    payload=LoopActionRequest(action=LoopActionKey.CONFIRM),
                    runtime_service=service,
                    dispatcher_admin_client=dispatcher_admin_stub,
                    session=session,
                    current_user_id=current_user_id,
                )
            assert dispatcher_admin_stub.confirm_calls == []
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_loop_control_act_confirm_forwards_force_flag(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(loop_action_endpoints, "ensure_loop_project_perm", _allow)
    monkeypatch.setattr(prediction_endpoints, "ensure_loop_project_perm", _allow)
    monkeypatch.setattr(snapshot_endpoints, "ensure_loop_project_perm", _allow)

    class _DispatcherAdminStub:
        def __init__(self) -> None:
            self.enabled = True
            self.confirm_calls: list[tuple[str, bool]] = []

        async def confirm_loop(self, loop_id: str, force: bool = False):
            self.confirm_calls.append((loop_id, force))

            class _Resp:
                command_id = "cmd-confirm"
                message = "confirm dispatched"

            return _Resp()

    dispatcher_admin_stub = _DispatcherAdminStub()

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-al-confirm",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config=_loop_config({"sampling": {"strategy": "random_baseline", "topk": 200}}),
                    lifecycle=LoopLifecycle.RUNNING,
                ),
            )

            async def _resolve_loop_action_request(**kwargs):
                del kwargs
                return (
                    {"loop_id": loop.id},
                    LoopActionKey.CONFIRM.value,
                    {"key": LoopActionKey.CONFIRM.value, "runnable": True, "payload": {}},
                )

            async def _get_loop_gate(**kwargs):
                del kwargs
                return {
                    "loop_id": loop.id,
                    "gate": "running",
                    "gate_meta": {},
                    "primary_action": None,
                    "actions": [],
                    "decision_token": "token",
                    "blocking_reasons": [],
                }

            monkeypatch.setattr(service, "resolve_loop_action_request", _resolve_loop_action_request)
            monkeypatch.setattr(service, "get_loop_gate", _get_loop_gate)

            await loop_action_endpoints.act_loop(
                loop_id=loop.id,
                payload=LoopActionRequest(action=LoopActionKey.CONFIRM, force=True),
                runtime_service=service,
                dispatcher_admin_client=dispatcher_admin_stub,
                session=session,
                current_user_id=current_user_id,
            )
            assert dispatcher_admin_stub.confirm_calls == [(str(loop.id), True)]
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_loop_control_act_rejects_selection_adjust(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(loop_action_endpoints, "ensure_loop_project_perm", _allow)
    monkeypatch.setattr(prediction_endpoints, "ensure_loop_project_perm", _allow)
    monkeypatch.setattr(snapshot_endpoints, "ensure_loop_project_perm", _allow)

    class _DispatcherAdminStub:
        enabled = True

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-selection-adjust-reject",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config=_loop_config({"sampling": {"strategy": "random_baseline", "topk": 200}}),
                    lifecycle=LoopLifecycle.RUNNING,
                ),
            )

            async def _resolve_loop_action_request(**kwargs):
                del kwargs
                return (
                    {"loop_id": loop.id},
                    LoopActionKey.SELECTION_ADJUST.value,
                    {"key": LoopActionKey.SELECTION_ADJUST.value, "runnable": True, "payload": {}},
                )

            monkeypatch.setattr(service, "resolve_loop_action_request", _resolve_loop_action_request)

            with pytest.raises(BadRequestAppException, match="unsupported action"):
                await loop_action_endpoints.act_loop(
                    loop_id=loop.id,
                    payload=LoopActionRequest(action=LoopActionKey.SELECTION_ADJUST),
                    runtime_service=service,
                    dispatcher_admin_client=_DispatcherAdminStub(),
                    session=session,
                    current_user_id=current_user_id,
                )
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_cleanup_round_predictions_writes_audit_log(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(loop_action_endpoints, "ensure_loop_project_perm", _allow)
    monkeypatch.setattr(prediction_endpoints, "ensure_loop_project_perm", _allow)
    monkeypatch.setattr(snapshot_endpoints, "ensure_loop_project_perm", _allow)

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-cleanup-audit",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config=_loop_config({"sampling": {"strategy": "random_baseline", "topk": 200}}),
                    lifecycle=LoopLifecycle.RUNNING,
                ),
            )
            loop_sampling = loop.config.get("sampling") if isinstance(loop.config, dict) else {}
            loop_strategy = str((loop_sampling or {}).get("strategy") or "random_baseline")
            round_row = Round(
                project_id=project.id,
                loop_id=loop.id,
                round_index=1,
                mode=LoopMode.ACTIVE_LEARNING,
                state=RoundStatus.RUNNING,
                step_counts={},
                round_type="loop_round",
                plugin_id=loop.model_arch,
                resolved_params={"sampling": {"strategy": loop_strategy}},
                resources={},
                input_commit_id=branch.head_commit_id,
                final_metrics={},
                final_artifacts={},
                strategy_params={"sampling": {"strategy": loop_strategy}},
            )
            session.add(round_row)
            await session.flush()

            step = Step(
                round_id=round_row.id,
                step_type=StepType.SCORE,
                dispatch_kind=StepDispatchKind.DISPATCHABLE,
                state=StepStatus.SUCCEEDED,
                round_index=1,
                step_index=1,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            await _attach_step_task(
                session,
                project_id=project.id,
                step=step,
                plugin_id=loop.model_arch,
            )
            session.add(
                TaskEvent(
                    task_id=step.task_id,
                    seq=1,
                    ts=datetime.now(UTC),
                    event_type="metric",
                    payload={"name": "map50"},
                )
            )
            session.add(
                TaskMetricPoint(
                    task_id=step.task_id,
                    metric_step=1,
                    epoch=1,
                    metric_name="map50",
                    metric_value=0.7,
                    ts=datetime.now(UTC),
                )
            )
            await session.commit()

            response = await prediction_endpoints.cleanup_round_predictions(
                loop_id=loop.id,
                round_index=1,
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert response.event_rows_deleted == 1
            assert response.metric_rows_deleted == 1

            audit_rows = list(
                (
                    await session.exec(
                        select(AuditLog).where(
                            AuditLog.target_id == round_row.id,
                            AuditLog.target_type == "runtime.cleanup_round_predictions",
                        )
                    )
                ).all()
            )
            assert len(audit_rows) == 1
            assert audit_rows[0].new_value["loop_id"] == str(loop.id)
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_get_task_events_query_contract(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(round_step_query_endpoint, "ensure_project_permission", _allow)

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-step-events",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config=_loop_config({"sampling": {"strategy": "random_baseline", "topk": 20}}),
                    lifecycle=LoopLifecycle.RUNNING,
                ),
            )
            round_row = Round(
                project_id=project.id,
                loop_id=loop.id,
                round_index=1,
                mode=LoopMode.ACTIVE_LEARNING,
                state=RoundStatus.RUNNING,
                step_counts={},
                round_type="loop_round",
                plugin_id=loop.model_arch,
                resolved_params={"sampling": {"strategy": "random_baseline"}},
                resources={},
                input_commit_id=branch.head_commit_id,
                final_metrics={},
                final_artifacts={},
                strategy_params={"sampling": {"strategy": "random_baseline"}},
            )
            session.add(round_row)
            await session.flush()

            step = Step(
                round_id=round_row.id,
                step_type=StepType.TRAIN,
                dispatch_kind=StepDispatchKind.DISPATCHABLE,
                state=StepStatus.RUNNING,
                round_index=1,
                step_index=1,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            await _attach_step_task(
                session,
                project_id=project.id,
                step=step,
                plugin_id=loop.model_arch,
            )

            session.add_all(
                    [
                        TaskEvent(
                            task_id=step.task_id,
                            seq=1,
                            ts=datetime.now(UTC),
                            event_type="log",
                            payload={"level": "INFO", "message": "train started", "tag": "trainer"},
                        ),
                        TaskEvent(
                            task_id=step.task_id,
                            seq=2,
                            ts=datetime.now(UTC),
                            event_type="status",
                            payload={"status": "running", "reason": "epoch 1"},
                        ),
                        TaskEvent(
                            task_id=step.task_id,
                            seq=3,
                            ts=datetime.now(UTC),
                            event_type="log",
                            payload={"level": "ERROR", "message": "disk full", "tags": ["io", "critical"]},
                        ),
                        TaskEvent(
                            task_id=step.task_id,
                            seq=4,
                            ts=datetime.now(UTC),
                            event_type="metric",
                        payload={"step": 1, "epoch": 1, "metrics": {"map50": 0.7, "precision": 0.8}},
                    ),
                ]
            )
            await session.commit()
            assert step.task_id is not None

            all_events = await round_step_query_endpoint.get_task_events(
                task_id=step.task_id,
                after_seq=0,
                limit=5000,
                include_facets=True,
                event_types=None,
                levels=None,
                tags=None,
                q=None,
                from_ts=None,
                to_ts=None,
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert len(all_events.items) == 4
            assert all_events.next_after_seq == 4
            assert all_events.facets is not None
            assert all_events.facets.event_types.get("log") == 2
            assert all_events.facets.event_types.get("metric") == 1
            assert all_events.facets.levels.get("INFO") == 1
            assert all_events.facets.levels.get("ERROR") == 1
            assert any("trainer" in item.tags for item in all_events.items)
            assert any(item.message_text == "disk full" for item in all_events.items)
            assert any(item.raw_message == "disk full" for item in all_events.items)
            metric_event = next(item for item in all_events.items if item.event_type == "metric")
            assert metric_event.message_key == "runtime.metric.update"
            assert "map50=0.7" in metric_event.message_text
            assert "precision=0.8" in metric_event.message_text

            error_only = await round_step_query_endpoint.get_task_events(
                task_id=step.task_id,
                after_seq=0,
                limit=5000,
                event_types=None,
                levels="ERROR",
                tags=None,
                q=None,
                from_ts=None,
                to_ts=None,
                include_facets=False,
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert len(error_only.items) == 1
            assert error_only.items[0].seq == 3

            io_tag_only = await round_step_query_endpoint.get_task_events(
                task_id=step.task_id,
                after_seq=0,
                limit=5000,
                event_types=None,
                levels=None,
                tags="io",
                q=None,
                from_ts=None,
                to_ts=None,
                include_facets=False,
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert len(io_tag_only.items) == 1
            assert io_tag_only.items[0].seq == 3

            status_only = await round_step_query_endpoint.get_task_events(
                task_id=step.task_id,
                after_seq=0,
                limit=5000,
                event_types="status",
                levels=None,
                tags=None,
                q=None,
                from_ts=None,
                to_ts=None,
                include_facets=False,
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert len(status_only.items) == 1
            assert status_only.items[0].seq == 2

            message_search = await round_step_query_endpoint.get_task_events(
                task_id=step.task_id,
                after_seq=0,
                limit=5000,
                event_types=None,
                levels=None,
                tags=None,
                q="disk",
                from_ts=None,
                to_ts=None,
                include_facets=False,
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert len(message_search.items) == 1
            assert message_search.items[0].seq == 3
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_get_round_events_query_contract(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(round_step_query_endpoint, "ensure_project_permission", _allow)

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-round-events",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config=_loop_config({"sampling": {"strategy": "random_baseline", "topk": 20}}),
                    lifecycle=LoopLifecycle.RUNNING,
                ),
            )
            round_row = Round(
                project_id=project.id,
                loop_id=loop.id,
                round_index=1,
                mode=LoopMode.ACTIVE_LEARNING,
                state=RoundStatus.RUNNING,
                step_counts={},
                round_type="loop_round",
                plugin_id=loop.model_arch,
                resolved_params={"sampling": {"strategy": "random_baseline"}},
                resources={},
                input_commit_id=branch.head_commit_id,
                final_metrics={},
                final_artifacts={},
                strategy_params={"sampling": {"strategy": "random_baseline"}},
            )
            session.add(round_row)
            await session.flush()

            train_step = Step(
                round_id=round_row.id,
                step_type=StepType.TRAIN,
                dispatch_kind=StepDispatchKind.DISPATCHABLE,
                state=StepStatus.RUNNING,
                round_index=1,
                step_index=1,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            eval_step = Step(
                round_id=round_row.id,
                step_type=StepType.EVAL,
                dispatch_kind=StepDispatchKind.DISPATCHABLE,
                state=StepStatus.PENDING,
                round_index=1,
                step_index=2,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            await _attach_step_task(
                session,
                project_id=project.id,
                step=train_step,
                plugin_id=loop.model_arch,
            )
            await _attach_step_task(
                session,
                project_id=project.id,
                step=eval_step,
                plugin_id=loop.model_arch,
            )

            session.add_all(
                [
                    TaskEvent(
                        task_id=train_step.task_id,
                        seq=1,
                        ts=datetime.now(UTC),
                        event_type="log",
                        payload={"level": "INFO", "message": "train started"},
                    ),
                    TaskEvent(
                        task_id=eval_step.task_id,
                        seq=1,
                        ts=datetime.now(UTC),
                        event_type="status",
                        payload={"status": "pending", "reason": "wait train"},
                    ),
                ]
            )
            await session.commit()

            first_page = await round_step_query_endpoint.get_round_events(
                round_id=round_row.id,
                after_cursor=None,
                limit=5000,
                stages=None,
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert len(first_page.items) == 2
            assert first_page.has_more is False
            assert first_page.next_after_cursor
            assert {item.stage for item in first_page.items} == {"train", "eval"}

            second_page = await round_step_query_endpoint.get_round_events(
                round_id=round_row.id,
                after_cursor=first_page.next_after_cursor,
                limit=5000,
                stages=None,
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert len(second_page.items) == 0

            train_only = await round_step_query_endpoint.get_round_events(
                round_id=round_row.id,
                after_cursor=None,
                limit=5000,
                stages="train",
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert len(train_only.items) == 1
            assert train_only.items[0].stage == "train"
            assert train_only.items[0].task_type == RuntimeTaskType.TRAIN

            with pytest.raises(BadRequestAppException):
                await round_step_query_endpoint.get_round_events(
                    round_id=round_row.id,
                    after_cursor="not-valid-cursor",
                    limit=5000,
                    stages=None,
                    runtime_service=service,
                    session=session,
                    current_user_id=current_user_id,
                )
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_get_round_prefers_eval_metrics_as_final_metrics(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(round_step_query_endpoint, "ensure_project_permission", _allow)

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-round-final-metrics",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config=_loop_config({"sampling": {"strategy": "random_baseline", "topk": 20}}),
                    lifecycle=LoopLifecycle.RUNNING,
                ),
            )
            round_row = Round(
                project_id=project.id,
                loop_id=loop.id,
                round_index=1,
                mode=LoopMode.ACTIVE_LEARNING,
                state=RoundStatus.COMPLETED,
                step_counts={"succeeded": 3},
                round_type="loop_round",
                plugin_id=loop.model_arch,
                resolved_params={"sampling": {"strategy": "random_baseline"}},
                resources={},
                input_commit_id=branch.head_commit_id,
                final_metrics={"map50": 0.11},
                final_artifacts={},
                strategy_params={"sampling": {"strategy": "random_baseline"}},
            )
            session.add(round_row)
            await session.flush()

            train_step = Step(
                round_id=round_row.id,
                step_type=StepType.TRAIN,
                dispatch_kind=StepDispatchKind.DISPATCHABLE,
                state=StepStatus.SUCCEEDED,
                round_index=1,
                step_index=1,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={"loss": 0.52, "invalid_label_count": 8.0},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            eval_step = Step(
                round_id=round_row.id,
                step_type=StepType.EVAL,
                dispatch_kind=StepDispatchKind.DISPATCHABLE,
                state=StepStatus.SUCCEEDED,
                round_index=1,
                step_index=2,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={"map50": 0.83, "precision": 0.91, "recall": 0.78},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            select_step = Step(
                round_id=round_row.id,
                step_type=StepType.SELECT,
                dispatch_kind=StepDispatchKind.ORCHESTRATOR,
                state=StepStatus.SUCCEEDED,
                round_index=1,
                step_index=3,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            await _attach_step_task_with_result_metrics(
                session,
                project_id=project.id,
                step=train_step,
                plugin_id=loop.model_arch,
                result_metrics={"loss": 0.52, "invalid_label_count": 8.0},
            )
            await _attach_step_task_with_result_metrics(
                session,
                project_id=project.id,
                step=eval_step,
                plugin_id=loop.model_arch,
                result_metrics={"map50": 0.83, "precision": 0.91, "recall": 0.78},
            )
            await _attach_step_task_with_result_metrics(
                session,
                project_id=project.id,
                step=select_step,
                plugin_id=loop.model_arch,
                result_metrics=None,
            )
            await session.commit()

            payload = await round_step_query_endpoint.get_round(
                round_id=round_row.id,
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert payload.final_metrics == {"map50": 0.83, "precision": 0.91, "recall": 0.78}
            assert payload.train_final_metrics == {"loss": 0.52, "invalid_label_count": 8.0}
            assert payload.eval_final_metrics == {"map50": 0.83, "precision": 0.91, "recall": 0.78}
            assert payload.final_metrics_source == "eval"
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_get_round_falls_back_to_train_when_eval_step_metrics_empty(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(round_step_query_endpoint, "ensure_project_permission", _allow)

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-round-final-metrics-from-series",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config=_loop_config({"sampling": {"strategy": "random_baseline", "topk": 20}}),
                    lifecycle=LoopLifecycle.RUNNING,
                ),
            )
            round_row = Round(
                project_id=project.id,
                loop_id=loop.id,
                round_index=1,
                mode=LoopMode.ACTIVE_LEARNING,
                state=RoundStatus.COMPLETED,
                step_counts={"succeeded": 3},
                round_type="loop_round",
                plugin_id=loop.model_arch,
                resolved_params={"sampling": {"strategy": "random_baseline"}},
                resources={},
                input_commit_id=branch.head_commit_id,
                final_metrics={"map50": 0.09},
                final_artifacts={},
                strategy_params={"sampling": {"strategy": "random_baseline"}},
            )
            session.add(round_row)
            await session.flush()

            train_step = Step(
                round_id=round_row.id,
                step_type=StepType.TRAIN,
                dispatch_kind=StepDispatchKind.DISPATCHABLE,
                state=StepStatus.SUCCEEDED,
                round_index=1,
                step_index=1,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={"loss": 0.61, "invalid_label_count": 7.0},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            eval_step = Step(
                round_id=round_row.id,
                step_type=StepType.EVAL,
                dispatch_kind=StepDispatchKind.DISPATCHABLE,
                state=StepStatus.SUCCEEDED,
                round_index=1,
                step_index=2,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            select_step = Step(
                round_id=round_row.id,
                step_type=StepType.SELECT,
                dispatch_kind=StepDispatchKind.ORCHESTRATOR,
                state=StepStatus.SUCCEEDED,
                round_index=1,
                step_index=3,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            train_task = await _attach_step_task_with_result_metrics(
                session,
                project_id=project.id,
                step=train_step,
                plugin_id=loop.model_arch,
                result_metrics={"loss": 0.61, "invalid_label_count": 7.0},
            )
            eval_task = await _attach_step_task_with_result_metrics(
                session,
                project_id=project.id,
                step=eval_step,
                plugin_id=loop.model_arch,
                result_metrics=None,
            )
            await _attach_step_task_with_result_metrics(
                session,
                project_id=project.id,
                step=select_step,
                plugin_id=loop.model_arch,
                result_metrics=None,
            )

            now = datetime.now(UTC)
            session.add_all(
                [
                    TaskMetricPoint(
                            task_id=eval_task.id,
                        metric_step=0,
                        epoch=0,
                        metric_name="map50",
                        metric_value=0.1,
                        ts=now,
                    ),
                    TaskMetricPoint(
                            task_id=eval_task.id,
                        metric_step=1,
                        epoch=1,
                        metric_name="map50",
                        metric_value=0.82,
                        ts=now,
                    ),
                    TaskMetricPoint(
                            task_id=eval_task.id,
                        metric_step=1,
                        epoch=1,
                        metric_name="precision",
                        metric_value=0.9,
                        ts=now,
                    ),
                    TaskMetricPoint(
                            task_id=eval_task.id,
                        metric_step=2,
                        epoch=2,
                        metric_name="map50",
                        metric_value=0.86,
                        ts=now,
                    ),
                ]
            )
            await session.commit()

            payload = await round_step_query_endpoint.get_round(
                round_id=round_row.id,
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert payload.final_metrics == {"loss": 0.61, "invalid_label_count": 7.0}
            assert payload.train_final_metrics == {"loss": 0.61, "invalid_label_count": 7.0}
            assert payload.eval_final_metrics == {}
            assert payload.final_metrics_source == "train"
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_get_round_metric_view_empty_when_all_steps_missing_metrics(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(round_step_query_endpoint, "ensure_project_permission", _allow)

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-round-metrics-empty",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config=_loop_config({"sampling": {"strategy": "random_baseline", "topk": 20}}),
                    lifecycle=LoopLifecycle.RUNNING,
                ),
            )
            round_row = Round(
                project_id=project.id,
                loop_id=loop.id,
                round_index=1,
                mode=LoopMode.ACTIVE_LEARNING,
                state=RoundStatus.COMPLETED,
                step_counts={"succeeded": 3},
                round_type="loop_round",
                plugin_id=loop.model_arch,
                resolved_params={"sampling": {"strategy": "random_baseline"}},
                resources={},
                input_commit_id=branch.head_commit_id,
                final_metrics={"map50": 0.2},
                final_artifacts={},
                strategy_params={"sampling": {"strategy": "random_baseline"}},
            )
            session.add(round_row)
            await session.flush()

            train_step = Step(
                round_id=round_row.id,
                step_type=StepType.TRAIN,
                dispatch_kind=StepDispatchKind.DISPATCHABLE,
                state=StepStatus.SUCCEEDED,
                round_index=1,
                step_index=1,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            eval_step = Step(
                round_id=round_row.id,
                step_type=StepType.EVAL,
                dispatch_kind=StepDispatchKind.DISPATCHABLE,
                state=StepStatus.SUCCEEDED,
                round_index=1,
                step_index=2,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            select_step = Step(
                round_id=round_row.id,
                step_type=StepType.SELECT,
                dispatch_kind=StepDispatchKind.ORCHESTRATOR,
                state=StepStatus.SUCCEEDED,
                round_index=1,
                step_index=3,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            await _attach_step_task(session, project_id=project.id, step=train_step, plugin_id=loop.model_arch)
            await _attach_step_task(session, project_id=project.id, step=eval_step, plugin_id=loop.model_arch)
            await _attach_step_task(session, project_id=project.id, step=select_step, plugin_id=loop.model_arch)
            await session.commit()

            payload = await round_step_query_endpoint.get_round(
                round_id=round_row.id,
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert payload.final_metrics == {}
            assert payload.train_final_metrics == {}
            assert payload.eval_final_metrics == {}
            assert payload.final_metrics_source == "none"
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_get_loop_summary_returns_split_metric_views(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(loop_query_endpoint, "_ensure_project_perm", _allow)

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-summary-split-metrics",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config=_loop_config({"sampling": {"strategy": "random_baseline", "topk": 20}}),
                    lifecycle=LoopLifecycle.RUNNING,
                ),
            )
            round_row = Round(
                project_id=project.id,
                loop_id=loop.id,
                round_index=1,
                mode=LoopMode.ACTIVE_LEARNING,
                state=RoundStatus.COMPLETED,
                step_counts={"succeeded": 3},
                round_type="loop_round",
                plugin_id=loop.model_arch,
                resolved_params={"sampling": {"strategy": "random_baseline"}},
                resources={},
                input_commit_id=branch.head_commit_id,
                final_metrics={},
                final_artifacts={},
                strategy_params={"sampling": {"strategy": "random_baseline"}},
            )
            session.add(round_row)
            await session.flush()

            train_step = Step(
                round_id=round_row.id,
                step_type=StepType.TRAIN,
                dispatch_kind=StepDispatchKind.DISPATCHABLE,
                state=StepStatus.SUCCEEDED,
                round_index=1,
                step_index=1,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={"map50": 0.71, "loss": 0.43},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            eval_step = Step(
                round_id=round_row.id,
                step_type=StepType.EVAL,
                dispatch_kind=StepDispatchKind.DISPATCHABLE,
                state=StepStatus.SUCCEEDED,
                round_index=1,
                step_index=2,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={"map50": 0.82, "precision": 0.9},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            select_step = Step(
                round_id=round_row.id,
                step_type=StepType.SELECT,
                dispatch_kind=StepDispatchKind.ORCHESTRATOR,
                state=StepStatus.SUCCEEDED,
                round_index=1,
                step_index=3,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            await _attach_step_task_with_result_metrics(
                session,
                project_id=project.id,
                step=train_step,
                plugin_id=loop.model_arch,
                result_metrics={"map50": 0.71, "loss": 0.43},
            )
            await _attach_step_task_with_result_metrics(
                session,
                project_id=project.id,
                step=eval_step,
                plugin_id=loop.model_arch,
                result_metrics={"map50": 0.82, "precision": 0.9},
            )
            await _attach_step_task_with_result_metrics(
                session,
                project_id=project.id,
                step=select_step,
                plugin_id=loop.model_arch,
                result_metrics=None,
            )
            await session.commit()

            summary = await loop_query_endpoint.get_loop_summary(
                loop_id=loop.id,
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert summary.metrics_latest == {"map50": 0.82, "precision": 0.9}
            assert summary.metrics_latest_train == {"map50": 0.71, "loss": 0.43}
            assert summary.metrics_latest_eval == {"map50": 0.82, "precision": 0.9}
            assert summary.metrics_latest_source == "eval"
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_list_loop_rounds_returns_split_metric_views(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(loop_query_endpoint, "_ensure_project_perm", _allow)

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-round-list-split-metrics",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config=_loop_config({"sampling": {"strategy": "random_baseline", "topk": 20}}),
                    lifecycle=LoopLifecycle.RUNNING,
                ),
            )
            round_row = Round(
                project_id=project.id,
                loop_id=loop.id,
                round_index=1,
                mode=LoopMode.ACTIVE_LEARNING,
                state=RoundStatus.COMPLETED,
                step_counts={"succeeded": 3},
                round_type="loop_round",
                plugin_id=loop.model_arch,
                resolved_params={"sampling": {"strategy": "random_baseline"}},
                resources={},
                input_commit_id=branch.head_commit_id,
                final_metrics={},
                final_artifacts={},
                strategy_params={"sampling": {"strategy": "random_baseline"}},
            )
            session.add(round_row)
            await session.flush()

            train_step = Step(
                round_id=round_row.id,
                step_type=StepType.TRAIN,
                dispatch_kind=StepDispatchKind.DISPATCHABLE,
                state=StepStatus.SUCCEEDED,
                round_index=1,
                step_index=1,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={"map50": 0.74, "loss": 0.39},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            eval_step = Step(
                round_id=round_row.id,
                step_type=StepType.EVAL,
                dispatch_kind=StepDispatchKind.DISPATCHABLE,
                state=StepStatus.SUCCEEDED,
                round_index=1,
                step_index=2,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={"map50": 0.86, "precision": 0.91},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            select_step = Step(
                round_id=round_row.id,
                step_type=StepType.SELECT,
                dispatch_kind=StepDispatchKind.ORCHESTRATOR,
                state=StepStatus.SUCCEEDED,
                round_index=1,
                step_index=3,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            await _attach_step_task_with_result_metrics(
                session,
                project_id=project.id,
                step=train_step,
                plugin_id=loop.model_arch,
                result_metrics={"map50": 0.74, "loss": 0.39},
            )
            await _attach_step_task_with_result_metrics(
                session,
                project_id=project.id,
                step=eval_step,
                plugin_id=loop.model_arch,
                result_metrics={"map50": 0.86, "precision": 0.91},
            )
            await _attach_step_task_with_result_metrics(
                session,
                project_id=project.id,
                step=select_step,
                plugin_id=loop.model_arch,
                result_metrics=None,
            )
            await session.commit()

            rows = await loop_query_endpoint.list_loop_rounds(
                loop_id=loop.id,
                limit=50,
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert len(rows) == 1
            row = rows[0]
            assert row.final_metrics == {"map50": 0.86, "precision": 0.91}
            assert row.train_final_metrics == {"map50": 0.74, "loss": 0.39}
            assert row.eval_final_metrics == {"map50": 0.86, "precision": 0.91}
            assert row.final_metrics_source == "eval"
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_get_task_metric_series_ignores_non_positive_step_points(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(round_step_query_endpoint, "ensure_project_permission", _allow)

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-metric-series-filter",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config=_loop_config({"sampling": {"strategy": "random_baseline", "topk": 20}}),
                    lifecycle=LoopLifecycle.RUNNING,
                ),
            )
            round_row = Round(
                project_id=project.id,
                loop_id=loop.id,
                round_index=1,
                mode=LoopMode.ACTIVE_LEARNING,
                state=RoundStatus.RUNNING,
                step_counts={},
                round_type="loop_round",
                plugin_id=loop.model_arch,
                resolved_params={"sampling": {"strategy": "random_baseline"}},
                resources={},
                input_commit_id=branch.head_commit_id,
                final_metrics={},
                final_artifacts={},
                strategy_params={"sampling": {"strategy": "random_baseline"}},
            )
            session.add(round_row)
            await session.flush()

            step = Step(
                round_id=round_row.id,
                step_type=StepType.TRAIN,
                dispatch_kind=StepDispatchKind.DISPATCHABLE,
                state=StepStatus.RUNNING,
                round_index=1,
                step_index=1,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            await _attach_step_task(
                session,
                project_id=project.id,
                step=step,
                plugin_id=loop.model_arch,
            )

            session.add_all(
                [
                    TaskMetricPoint(
                        task_id=step.task_id,
                        metric_step=0,
                        epoch=None,
                        metric_name="map50",
                        metric_value=0.6,
                        ts=datetime.now(UTC),
                    ),
                    TaskMetricPoint(
                        task_id=step.task_id,
                        metric_step=1,
                        epoch=1,
                        metric_name="map50",
                        metric_value=0.7,
                        ts=datetime.now(UTC),
                    ),
                ]
            )
            await session.commit()

            series = await round_step_query_endpoint.get_task_metric_series(
                task_id=step.task_id,
                limit=5000,
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert len(series) == 1
            assert int(series[0].step) == 1
            assert float(series[0].metric_value) == pytest.approx(0.7)
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_list_round_steps_returns_depends_on_task_ids(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(round_step_query_endpoint, "ensure_project_permission", _allow)

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-step-task-deps",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config=_loop_config({"sampling": {"strategy": "random_baseline", "topk": 20}}),
                    lifecycle=LoopLifecycle.RUNNING,
                ),
            )
            round_row = Round(
                project_id=project.id,
                loop_id=loop.id,
                round_index=1,
                mode=LoopMode.ACTIVE_LEARNING,
                state=RoundStatus.RUNNING,
                step_counts={},
                round_type="loop_round",
                plugin_id=loop.model_arch,
                resolved_params={"sampling": {"strategy": "random_baseline"}},
                resources={},
                input_commit_id=branch.head_commit_id,
                final_metrics={},
                final_artifacts={},
                strategy_params={"sampling": {"strategy": "random_baseline"}},
            )
            session.add(round_row)
            await session.flush()

            train_step = Step(
                round_id=round_row.id,
                step_type=StepType.TRAIN,
                dispatch_kind=StepDispatchKind.DISPATCHABLE,
                state=StepStatus.RUNNING,
                round_index=1,
                step_index=1,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            eval_step = Step(
                round_id=round_row.id,
                step_type=StepType.EVAL,
                dispatch_kind=StepDispatchKind.DISPATCHABLE,
                state=StepStatus.PENDING,
                round_index=1,
                step_index=2,
                depends_on_step_ids=[str(train_step.id)] if train_step.id else [],
                resolved_params={},
                metrics={},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            train_task = await _attach_step_task(
                session,
                project_id=project.id,
                step=train_step,
                plugin_id=loop.model_arch,
            )
            eval_task = await _attach_step_task(
                session,
                project_id=project.id,
                step=eval_step,
                plugin_id=loop.model_arch,
            )
            eval_task.depends_on_task_ids = [str(train_task.id)]
            session.add(eval_task)
            await session.commit()

            rows = await round_step_query_endpoint.list_round_steps(
                round_id=round_row.id,
                limit=100,
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            by_index = {int(row.step_index): row for row in rows}
            assert by_index[1].depends_on_task_ids == []
            assert by_index[2].depends_on_task_ids == [str(train_task.id)]
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_list_round_steps_raises_when_step_task_binding_missing(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(round_step_query_endpoint, "ensure_project_permission", _allow)

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-step-missing-task-binding",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config=_loop_config({"sampling": {"strategy": "random_baseline", "topk": 20}}),
                    lifecycle=LoopLifecycle.RUNNING,
                ),
            )
            round_row = Round(
                project_id=project.id,
                loop_id=loop.id,
                round_index=1,
                mode=LoopMode.ACTIVE_LEARNING,
                state=RoundStatus.RUNNING,
                step_counts={},
                round_type="loop_round",
                plugin_id=loop.model_arch,
                resolved_params={"sampling": {"strategy": "random_baseline"}},
                resources={},
                input_commit_id=branch.head_commit_id,
                final_metrics={},
                final_artifacts={},
                strategy_params={"sampling": {"strategy": "random_baseline"}},
            )
            session.add(round_row)
            await session.flush()

            with pytest.raises(IntegrityError):
                step = Step(
                    round_id=round_row.id,
                    step_type=StepType.TRAIN,
                    dispatch_kind=StepDispatchKind.DISPATCHABLE,
                    state=StepStatus.PENDING,
                    round_index=1,
                    step_index=1,
                    depends_on_step_ids=[],
                    resolved_params={},
                    metrics={},
                    artifacts={},
                    input_commit_id=branch.head_commit_id,
                    attempt=1,
                    max_attempts=3,
                )
                session.add(step)
                await session.commit()
            await session.rollback()
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_list_loop_rounds_raises_when_step_task_binding_missing(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(loop_query_endpoint, "_ensure_project_perm", _allow)

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-rounds-missing-task-binding",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config=_loop_config({"sampling": {"strategy": "random_baseline", "topk": 20}}),
                    lifecycle=LoopLifecycle.RUNNING,
                ),
            )
            round_row = Round(
                project_id=project.id,
                loop_id=loop.id,
                round_index=1,
                mode=LoopMode.ACTIVE_LEARNING,
                state=RoundStatus.COMPLETED,
                step_counts={"pending": 1},
                round_type="loop_round",
                plugin_id=loop.model_arch,
                resolved_params={"sampling": {"strategy": "random_baseline"}},
                resources={},
                input_commit_id=branch.head_commit_id,
                final_metrics={},
                final_artifacts={},
                strategy_params={"sampling": {"strategy": "random_baseline"}},
            )
            session.add(round_row)
            await session.flush()

            with pytest.raises(IntegrityError):
                step = Step(
                    round_id=round_row.id,
                    step_type=StepType.TRAIN,
                    dispatch_kind=StepDispatchKind.DISPATCHABLE,
                    state=StepStatus.PENDING,
                    round_index=1,
                    step_index=1,
                    depends_on_step_ids=[],
                    resolved_params={},
                    metrics={},
                    artifacts={},
                    input_commit_id=branch.head_commit_id,
                    attempt=1,
                    max_attempts=3,
                )
                session.add(step)
                await session.commit()
            await session.rollback()
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_get_round_prefers_task_result_metrics_over_step_projection(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(round_step_query_endpoint, "ensure_project_permission", _allow)

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-round-task-metrics-priority",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config=_loop_config({"sampling": {"strategy": "random_baseline", "topk": 20}}),
                    lifecycle=LoopLifecycle.RUNNING,
                ),
            )
            round_row = Round(
                project_id=project.id,
                loop_id=loop.id,
                round_index=1,
                mode=LoopMode.ACTIVE_LEARNING,
                state=RoundStatus.COMPLETED,
                step_counts={},
                round_type="loop_round",
                plugin_id=loop.model_arch,
                resolved_params={"sampling": {"strategy": "random_baseline"}},
                resources={},
                input_commit_id=branch.head_commit_id,
                final_metrics={},
                final_artifacts={},
                strategy_params={"sampling": {"strategy": "random_baseline"}},
            )
            session.add(round_row)
            await session.flush()

            step = Step(
                round_id=round_row.id,
                step_type=StepType.TRAIN,
                dispatch_kind=StepDispatchKind.DISPATCHABLE,
                state=StepStatus.SUCCEEDED,
                round_index=1,
                step_index=1,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={"map50": 0.11, "loss": 9.99},
                artifacts={},
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            task = await _attach_step_task(
                session,
                project_id=project.id,
                step=step,
                plugin_id=loop.model_arch,
            )
            task.resolved_params = {
                "_result_metrics": {"map50": 0.88, "loss": 0.22},
                "_result_artifacts": {},
            }
            session.add(task)
            await session.commit()

            payload = await round_step_query_endpoint.get_round(
                round_id=round_row.id,
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert float(payload.final_metrics.get("map50", 0.0)) == pytest.approx(0.88)
            assert float(payload.final_metrics.get("loss", 0.0)) == pytest.approx(0.22)
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_task_artifact_download_url_only_reads_task_artifacts(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-task-artifact-only",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config=_loop_config({"sampling": {"strategy": "random_baseline", "topk": 20}}),
                    lifecycle=LoopLifecycle.RUNNING,
                ),
            )
            round_row = Round(
                project_id=project.id,
                loop_id=loop.id,
                round_index=1,
                mode=LoopMode.ACTIVE_LEARNING,
                state=RoundStatus.RUNNING,
                step_counts={},
                round_type="loop_round",
                plugin_id=loop.model_arch,
                resolved_params={"sampling": {"strategy": "random_baseline"}},
                resources={},
                input_commit_id=branch.head_commit_id,
                final_metrics={},
                final_artifacts={},
                strategy_params={"sampling": {"strategy": "random_baseline"}},
            )
            session.add(round_row)
            await session.flush()

            step = Step(
                round_id=round_row.id,
                step_type=StepType.TRAIN,
                dispatch_kind=StepDispatchKind.DISPATCHABLE,
                state=StepStatus.SUCCEEDED,
                round_index=1,
                step_index=1,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={},
                artifacts={
                    "best.pt": {
                        "kind": "model",
                        "uri": "https://example.com/step-only-model.pt",
                        "meta": {},
                    }
                },
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            task = await _attach_step_task(
                session,
                project_id=project.id,
                step=step,
                plugin_id=loop.model_arch,
            )
            await session.commit()

            with pytest.raises(NotFoundAppException):
                await service.get_task_artifact_download_url(
                    task_id=task.id,
                    artifact_name="best.pt",
                    expires_in_hours=2,
                )

            params = dict(task.resolved_params or {})
            params["_result_artifacts"] = {
                "best.pt": {
                    "kind": "model",
                    "uri": "https://example.com/task-result-model.pt",
                    "meta": {"size": 1024},
                }
            }
            task.resolved_params = params
            session.add(task)
            await session.commit()

            download_url = await service.get_task_artifact_download_url(
                task_id=task.id,
                artifact_name="best.pt",
                expires_in_hours=2,
            )
            assert download_url == "https://example.com/task-result-model.pt"
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_list_round_artifacts_only_reads_task_artifacts(loop_api_env):
    session_local = loop_api_env

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)

        token = _session_ctx.set(session)
        try:
            loop = await service.create_loop(
                project.id,
                LoopCreateRequest(
                    name="loop-round-artifact-only",
                    branch_id=branch.id,
                    mode=LoopMode.ACTIVE_LEARNING,
                    model_arch="yolo_det_v1",
                    config=_loop_config({"sampling": {"strategy": "random_baseline", "topk": 20}}),
                    lifecycle=LoopLifecycle.RUNNING,
                ),
            )
            round_row = Round(
                project_id=project.id,
                loop_id=loop.id,
                round_index=1,
                mode=LoopMode.ACTIVE_LEARNING,
                state=RoundStatus.RUNNING,
                step_counts={},
                round_type="loop_round",
                plugin_id=loop.model_arch,
                resolved_params={"sampling": {"strategy": "random_baseline"}},
                resources={},
                input_commit_id=branch.head_commit_id,
                final_metrics={},
                final_artifacts={},
                strategy_params={"sampling": {"strategy": "random_baseline"}},
            )
            session.add(round_row)
            await session.flush()

            step = Step(
                round_id=round_row.id,
                step_type=StepType.TRAIN,
                dispatch_kind=StepDispatchKind.DISPATCHABLE,
                state=StepStatus.SUCCEEDED,
                round_index=1,
                step_index=1,
                depends_on_step_ids=[],
                resolved_params={},
                metrics={},
                artifacts={
                    "step-only.pt": {
                        "kind": "model",
                        "uri": "https://example.com/step-only-model.pt",
                        "meta": {},
                    }
                },
                input_commit_id=branch.head_commit_id,
                attempt=1,
                max_attempts=3,
            )
            task = await _attach_step_task(
                session,
                project_id=project.id,
                step=step,
                plugin_id=loop.model_arch,
            )
            await session.commit()

            items = await service.list_round_artifacts(round_id=round_row.id, limit=100)
            assert items == []

            params = dict(task.resolved_params or {})
            params["_result_artifacts"] = {
                "task-result.pt": {
                    "kind": "model",
                    "uri": "https://example.com/task-result-model.pt",
                    "meta": {"size": 2048},
                }
            }
            task.resolved_params = params
            session.add(task)
            await session.commit()

            items = await service.list_round_artifacts(round_id=round_row.id, limit=100)
            assert len(items) == 1
            assert items[0].name == "task-result.pt"
            assert str(items[0].task_id) == str(task.id)
            assert str(items[0].step_id) == str(step.id)
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_create_simulation_loop_normalizes_mode_without_seeds_or_random_baseline(
    loop_api_env,
    monkeypatch,
):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(loop_query_endpoint, "_ensure_project_perm", _allow)

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            created = await loop_query_endpoint.create_project_loop(
                project_id=project.id,
                payload=LoopCreateRequest(
                    name="sim-single-loop",
                    branch_id=branch.id,
                    mode=LoopMode.SIMULATION,
                    model_arch="yolo_det_v1",
                    config={
                        "sampling": {"strategy": "random_baseline", "topk": 200},
                        "reproducibility": {"global_seed": "seed-1"},
                        "mode": {
                            "oracle_commit_id": str(branch.head_commit_id),
                            "snapshot_init": {
                                "train_seed_ratio": 0.1,
                                "val_ratio": 0.2,
                                "test_ratio": 0.3,
                                "val_policy": "expand_with_batch_val",
                            },
                            "max_rounds": 7,
                            "seed_ratio": 0.1,
                            "step_ratio": 0.2,
                            "seeds": [0, 1, 2],
                            "random_baseline_enabled": True,
                        },
                    },
                ),
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert created.mode == LoopMode.SIMULATION
            mode_cfg = created.config.get("mode") if isinstance(created.config.get("mode"), dict) else {}
            assert mode_cfg.get("oracle_commit_id") == str(branch.head_commit_id)
            snapshot_init_cfg = mode_cfg.get("snapshot_init") if isinstance(mode_cfg.get("snapshot_init"), dict) else {}
            assert float(snapshot_init_cfg.get("train_seed_ratio")) == pytest.approx(0.1)
            assert float(snapshot_init_cfg.get("val_ratio")) == pytest.approx(0.2)
            assert float(snapshot_init_cfg.get("test_ratio")) == pytest.approx(0.3)
            assert str(snapshot_init_cfg.get("val_policy")) == "expand_with_batch_val"
            assert int(mode_cfg.get("max_rounds")) == 7
            assert "seed_ratio" not in mode_cfg
            assert "step_ratio" not in mode_cfg
            assert "seeds" not in mode_cfg
            assert "random_baseline_enabled" not in mode_cfg
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_update_simulation_loop_applies_mode_max_rounds(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(loop_query_endpoint, "_ensure_project_perm", _allow)

    async with session_local() as session:
        project, branch = await _seed_project_branch(session)
        service = RuntimeService(session)
        current_user_id = uuid.uuid4()

        token = _session_ctx.set(session)
        try:
            created = await loop_query_endpoint.create_project_loop(
                project_id=project.id,
                payload=LoopCreateRequest(
                    name="sim-update-max-rounds",
                    branch_id=branch.id,
                    mode=LoopMode.SIMULATION,
                    model_arch="yolo_det_v1",
                    config={
                        "sampling": {"strategy": "random_baseline", "topk": 200},
                        "reproducibility": {"global_seed": "seed-1"},
                        "mode": {
                            "oracle_commit_id": str(branch.head_commit_id),
                            "snapshot_init": {
                                "train_seed_ratio": 0.1,
                                "val_ratio": 0.2,
                                "test_ratio": 0.3,
                                "val_policy": "anchor_only",
                            },
                            "max_rounds": 7,
                        },
                    },
                ),
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert int(created.max_rounds) == 7

            updated = await loop_query_endpoint.update_loop(
                loop_id=created.id,
                payload=LoopUpdateRequest(
                    config={
                        "sampling": {"strategy": "random_baseline", "topk": 200},
                        "reproducibility": {"global_seed": "seed-1"},
                        "mode": {
                            "oracle_commit_id": str(branch.head_commit_id),
                            "snapshot_init": {
                                "train_seed_ratio": 0.15,
                                "val_ratio": 0.25,
                                "test_ratio": 0.35,
                                "val_policy": "expand_with_batch_val",
                            },
                            "max_rounds": 11,
                        },
                    },
                ),
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )
            assert int(updated.max_rounds) == 11
            mode_cfg = updated.config.get("mode") if isinstance(updated.config.get("mode"), dict) else {}
            assert int(mode_cfg.get("max_rounds")) == 11
            snapshot_init_cfg = mode_cfg.get("snapshot_init") if isinstance(mode_cfg.get("snapshot_init"), dict) else {}
            assert float(snapshot_init_cfg.get("train_seed_ratio")) == pytest.approx(0.15)
            assert float(snapshot_init_cfg.get("val_ratio")) == pytest.approx(0.25)
            assert float(snapshot_init_cfg.get("test_ratio")) == pytest.approx(0.35)
            assert str(snapshot_init_cfg.get("val_policy")) == "expand_with_batch_val"
        finally:
            _session_ctx.reset(token)
