from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from saki_executor.cache.asset_cache import AssetCache
from saki_executor.steps.orchestration.training_data_service import TrainingDataPlan
from saki_executor.steps.workspace import Workspace
from saki_executor.steps.workspace_adapter import WorkspaceAdapter
from saki_executor.steps.orchestration.pipeline_stage_service import PipelineStageService


def _make_bound_plan() -> SimpleNamespace:
    return SimpleNamespace(
        plan=SimpleNamespace(
            runtime_context=SimpleNamespace(
                mode="active_learning",
                split_seed=123,
            )
        ),
        effective_plugin_params={"batch": 16, "imgsz": 640},
    )


def test_data_cache_fingerprint_includes_task_type():
    bound_plan = _make_bound_plan()
    common_request = {
        "round_id": "round-1",
        "attempt": 1,
        "project_id": "project-1",
        "input_commit_id": "commit-1",
        "plugin_id": "yolo_det_v1",
    }
    train_service = PipelineStageService(
        manager=SimpleNamespace(),
        request=SimpleNamespace(task_type="train", **common_request),
    )
    eval_service = PipelineStageService(
        manager=SimpleNamespace(),
        request=SimpleNamespace(task_type="eval", **common_request),
    )

    train_fingerprint = train_service._build_data_cache_fingerprint(bound_plan=bound_plan)  # type: ignore[arg-type]
    eval_fingerprint = eval_service._build_data_cache_fingerprint(bound_plan=bound_plan)  # type: ignore[arg-type]
    assert train_fingerprint != eval_fingerprint


@pytest.mark.anyio
async def test_prepare_data_for_train_uses_prepared_data_cache_v2_hit(tmp_path, monkeypatch):
    manager = SimpleNamespace(
        round_shared_cache_enabled=True,
        stop_event=asyncio.Event(),
        cache=AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=10 * 1024 * 1024),
        fetch_all_data=None,
    )
    request = SimpleNamespace(
        task_id="task-train",
        round_id="round-1",
        task_type="train",
        resolved_params={},
        plugin_id="plugin-a",
        project_id="project-1",
        input_commit_id="commit-1",
    )
    service = PipelineStageService(manager=manager, request=request)
    workspace = WorkspaceAdapter(
        Workspace(
            str(tmp_path / "runs"),
            "task-train",
            round_id="round-1",
            attempt=1,
            prepared_data_cache_root=tmp_path / "cache" / "prepared_data_v2",
        )
    )
    workspace.ensure()
    (workspace.data_dir / "dataset_manifest.json").write_text("{}", encoding="utf-8")
    workspace.store_prepared_data_cache("prepared-fp", "source-task")
    if workspace.data_dir.exists():
        import shutil

        shutil.rmtree(workspace.data_dir)

    plan = TrainingDataPlan(
        labels=[],
        samples=[],
        train_annotations=[],
        splits={"train": [], "val": []},
        split_seed=0,
        val_ratio=0.2,
    )

    async def _unexpected_materialize(self, *, request, plan, emit):
        raise AssertionError("materialize_plan should not run on prepared cache hit")

    monkeypatch.setattr(
        "saki_executor.steps.orchestration.training_data_service.TrainingDataService.plan",
        lambda self, **kwargs: asyncio.sleep(0, result=plan),
    )
    monkeypatch.setattr(
        "saki_executor.steps.orchestration.training_data_service.TrainingDataService.build_prepared_data_cache_fingerprint",
        lambda self, **kwargs: "prepared-fp",
    )
    monkeypatch.setattr(
        "saki_executor.steps.orchestration.training_data_service.TrainingDataService.materialize_plan",
        _unexpected_materialize,
    )

    class _Plugin:
        async def prepare_data(self, **kwargs):
            raise AssertionError("plugin.prepare_data should not run on prepared cache hit")

    emitted: list[dict[str, object]] = []

    class _Emitter:
        async def emit(self, event_type: str, payload: dict):
            if event_type == "log":
                emitted.append(dict(payload))

    protected = await service._prepare_data_for_step(
        plugin=_Plugin(),
        workspace=workspace,
        emitter=_Emitter(),
        runtime_requirements=SimpleNamespace(requires_prepare_data=True),
        bound_plan=SimpleNamespace(
            plan=SimpleNamespace(
                runtime_context=SimpleNamespace(
                    mode="simulation",
                    task_type="train",
                    round_index=1,
                    task_id="task-train",
                    split_seed=3,
                    train_seed=4,
                    sampling_seed=5,
                )
            ),
            effective_plugin_params={"imgsz": 640},
        ),
    )

    assert protected == set()
    assert (workspace.data_dir / "dataset_manifest.json").exists()
    assert any("prepared data cache 命中" in str(item.get("message") or "") for item in emitted)
