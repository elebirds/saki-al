from __future__ import annotations

from datetime import UTC, datetime
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import saki_api.modules.shared.modeling  # noqa: F401
from saki_api.modules.access.domain.rbac.audit_log import AuditLog
from saki_api.modules.runtime.api.http import loop_control as loop_control_endpoint
from saki_api.modules.runtime.api.http import query as loop_query_endpoint
from saki_api.modules.runtime.api.http.endpoints import round_step_query_endpoints as round_step_query_endpoint
from saki_api.core.exceptions import BadRequestAppException
from saki_api.infra.db.session import _session_ctx
from saki_api.modules.shared.modeling.enums import (
    AuthorType,
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
)
from saki_api.modules.project.domain.branch import Branch
from saki_api.modules.project.domain.commit import Commit
from saki_api.modules.project.domain.project import Project
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.step_event import StepEvent
from saki_api.modules.runtime.domain.step_metric_point import StepMetricPoint
from saki_api.modules.runtime.api.round_step import (
    LoopActionRequest,
    LoopCreateRequest,
    LoopUpdateRequest,
    SimulationExperimentCreateRequest,
)
from saki_api.modules.runtime.service.runtime_service.snapshot_mixin import SnapshotMixin
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
                    config={
                        "plugin": {"epochs": 12, "batch": 8},
                        "sampling": {"strategy": "random_baseline", "topk": 200},
                    },
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
                    config={
                        "plugin": {"epochs": 24, "batch": 16},
                        "sampling": {"strategy": "random_baseline", "topk": 200},
                    },
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
                    config={
                        "plugin": {"epochs": 30, "lr": 0.001},
                        "sampling": {"strategy": "uncertainty_1_minus_max_conf", "topk": 256},
                    },
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
                    config={"sampling": {"strategy": "random_baseline", "topk": 200}},
                ),
            )
            with pytest.raises(BadRequestAppException):
                await service.create_loop(
                    project.id,
                    LoopCreateRequest(
                        name="loop-second",
                        branch_id=branch.id,
                        model_arch="yolo_det_v1",
                        config={"sampling": {"strategy": "random_baseline", "topk": 200}},
                    ),
                )
        finally:
            _session_ctx.reset(token)


def test_loop_control_legacy_entrypoints_removed():
    assert not hasattr(loop_control_endpoint, "confirm_loop")
    assert not hasattr(loop_control_endpoint, "continue_loop")
    assert not hasattr(loop_control_endpoint, "start_loop")
    assert not hasattr(loop_control_endpoint, "pause_loop")
    assert not hasattr(loop_control_endpoint, "resume_loop")
    assert not hasattr(loop_control_endpoint, "stop_loop")


def test_effective_round_min_required_requires_full_selected():
    assert SnapshotMixin._effective_round_min_required(selected_count=0, configured_min_required=1) == 0
    assert SnapshotMixin._effective_round_min_required(selected_count=2, configured_min_required=1) == 2
    assert SnapshotMixin._effective_round_min_required(selected_count=5, configured_min_required=2) == 5


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
                    config={"sampling": {"strategy": "random_baseline", "topk": 200}},
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
async def test_loop_control_act_confirm_rejects_manual_mode(loop_api_env, monkeypatch):
    session_local = loop_api_env

    async def _allow(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(loop_control_endpoint, "_ensure_project_perm", _allow)

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
                    config={"plugin": {"epochs": 1}},
                    lifecycle=LoopLifecycle.RUNNING,
                ),
            )
            loop.phase = LoopPhase.MANUAL_EVAL
            session.add(loop)
            await session.commit()
            await session.refresh(loop)

            with pytest.raises(BadRequestAppException):
                await loop_control_endpoint.act_loop(
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

    monkeypatch.setattr(loop_control_endpoint, "_ensure_project_perm", _allow)

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
                    config={"sampling": {"strategy": "random_baseline", "topk": 200}},
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

            await loop_control_endpoint.act_loop(
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

    monkeypatch.setattr(loop_control_endpoint, "_ensure_project_perm", _allow)

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
                    config={"sampling": {"strategy": "random_baseline", "topk": 200}},
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
                await loop_control_endpoint.act_loop(
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

    monkeypatch.setattr(loop_control_endpoint, "_ensure_project_perm", _allow)

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
                    config={"sampling": {"strategy": "random_baseline", "topk": 200}},
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
            session.add(step)
            await session.flush()
            session.add(
                StepEvent(
                    step_id=step.id,
                    seq=1,
                    ts=datetime.now(UTC),
                    event_type="metric",
                    payload={"name": "map50"},
                )
            )
            session.add(
                StepMetricPoint(
                    step_id=step.id,
                    metric_step=1,
                    epoch=1,
                    metric_name="map50",
                    metric_value=0.7,
                    ts=datetime.now(UTC),
                )
            )
            await session.commit()

            response = await loop_control_endpoint.cleanup_round_predictions(
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
async def test_get_step_events_query_contract(loop_api_env, monkeypatch):
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
                    config={"sampling": {"strategy": "random_baseline", "topk": 20}},
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
            session.add(step)
            await session.flush()

            session.add_all(
                [
                    StepEvent(
                        step_id=step.id,
                        seq=1,
                        ts=datetime.now(UTC),
                        event_type="log",
                        payload={"level": "INFO", "message": "train started", "tag": "trainer"},
                    ),
                    StepEvent(
                        step_id=step.id,
                        seq=2,
                        ts=datetime.now(UTC),
                        event_type="status",
                        payload={"status": "running", "reason": "epoch 1"},
                    ),
                    StepEvent(
                        step_id=step.id,
                        seq=3,
                        ts=datetime.now(UTC),
                        event_type="log",
                        payload={"level": "ERROR", "message": "disk full", "tags": ["io", "critical"]},
                    ),
                    StepEvent(
                        step_id=step.id,
                        seq=4,
                        ts=datetime.now(UTC),
                        event_type="metric",
                        payload={"step": 1, "epoch": 1, "metrics": {"map50": 0.7, "precision": 0.8}},
                    ),
                ]
            )
            await session.commit()

            all_events = await round_step_query_endpoint.get_step_events(
                step_id=step.id,
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
            assert metric_event.message_text != "metric keys=map50,precision"

            error_only = await round_step_query_endpoint.get_step_events(
                step_id=step.id,
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

            io_tag_only = await round_step_query_endpoint.get_step_events(
                step_id=step.id,
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

            status_only = await round_step_query_endpoint.get_step_events(
                step_id=step.id,
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

            message_search = await round_step_query_endpoint.get_step_events(
                step_id=step.id,
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
                    config={"sampling": {"strategy": "random_baseline", "topk": 20}},
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
            session.add_all([train_step, eval_step])
            await session.flush()

            session.add_all(
                [
                    StepEvent(
                        step_id=train_step.id,
                        seq=1,
                        ts=datetime.now(UTC),
                        event_type="log",
                        payload={"level": "INFO", "message": "train started"},
                    ),
                    StepEvent(
                        step_id=eval_step.id,
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
            assert train_only.items[0].step_type == StepType.TRAIN

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
                    config={"sampling": {"strategy": "random_baseline", "topk": 20}},
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

            session.add_all(
                [
                    Step(
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
                    ),
                    Step(
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
                    ),
                    Step(
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
            assert payload.final_metrics == {"map50": 0.83, "precision": 0.91, "recall": 0.78}
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
                    config={"sampling": {"strategy": "random_baseline", "topk": 20}},
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
            session.add_all([train_step, eval_step, select_step])
            await session.flush()

            now = datetime.now(UTC)
            session.add_all(
                [
                    StepMetricPoint(
                        step_id=eval_step.id,
                        metric_step=0,
                        epoch=0,
                        metric_name="map50",
                        metric_value=0.1,
                        ts=now,
                    ),
                    StepMetricPoint(
                        step_id=eval_step.id,
                        metric_step=1,
                        epoch=1,
                        metric_name="map50",
                        metric_value=0.82,
                        ts=now,
                    ),
                    StepMetricPoint(
                        step_id=eval_step.id,
                        metric_step=1,
                        epoch=1,
                        metric_name="precision",
                        metric_value=0.9,
                        ts=now,
                    ),
                    StepMetricPoint(
                        step_id=eval_step.id,
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
        finally:
            _session_ctx.reset(token)


@pytest.mark.anyio
async def test_get_step_metric_series_ignores_non_positive_step_points(loop_api_env, monkeypatch):
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
                    config={"sampling": {"strategy": "random_baseline", "topk": 20}},
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
            session.add(step)
            await session.flush()

            session.add_all(
                [
                    StepMetricPoint(
                        step_id=step.id,
                        metric_step=0,
                        epoch=None,
                        metric_name="map50",
                        metric_value=0.6,
                        ts=datetime.now(UTC),
                    ),
                    StepMetricPoint(
                        step_id=step.id,
                        metric_step=1,
                        epoch=1,
                        metric_name="map50",
                        metric_value=0.7,
                        ts=datetime.now(UTC),
                    ),
                ]
            )
            await session.commit()

            series = await round_step_query_endpoint.get_step_metric_series(
                step_id=step.id,
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
async def test_simulation_experiment_create_and_comparison_contract(loop_api_env, monkeypatch):
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
            created = await loop_query_endpoint.create_simulation_experiment(
                project_id=project.id,
                payload=SimulationExperimentCreateRequest(
                    branch_id=branch.id,
                    experiment_name="sim-exp",
                    model_arch="yolo_det_v1",
                    strategies=["uncertainty_1_minus_max_conf"],
                    config={
                        "sampling": {"strategy": "random_baseline", "topk": 200},
                        "mode": {
                            "oracle_commit_id": str(branch.head_commit_id),
                            "seed_ratio": 0.1,
                            "step_ratio": 0.1,
                            "max_rounds": 3,
                            "seeds": [0, 1],
                        },
                    },
                ),
                runtime_service=service,
                session=session,
                current_user_id=current_user_id,
            )

            # random_baseline + one strategy, each with 2 seeds
            assert len(created.loops) == 4
            assert all(loop.mode == LoopMode.SIMULATION for loop in created.loops)

            for loop in created.loops:
                loop_sampling = loop.config.get("sampling") if isinstance(loop.config, dict) else {}
                loop_strategy = str((loop_sampling or {}).get("strategy") or "random_baseline")
                for ridx in [1, 2, 3]:
                    base = 0.5 if loop_strategy == "random_baseline" else 0.6
                    session.add(
                        Round(
                            project_id=project.id,
                            loop_id=loop.id,
                            round_index=ridx,
                            mode=LoopMode.SIMULATION,
                            state=RoundStatus.COMPLETED,
                            step_counts={"succeeded": 4},
                            round_type="loop_round",
                            plugin_id=loop.model_arch,
                            resolved_params={"sampling": {"strategy": loop_strategy}},
                            resources={},
                            input_commit_id=branch.head_commit_id,
                            final_metrics={"map50": base + ridx * 0.01},
                            final_artifacts={},
                            strategy_params={"sampling": {"strategy": loop_strategy}},
                        )
                    )
            await session.commit()

            comparison = await loop_query_endpoint.get_simulation_experiment_comparison(
                group_id=created.experiment_group_id,
                metric_name="map50",
                runtime_service=service,
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
