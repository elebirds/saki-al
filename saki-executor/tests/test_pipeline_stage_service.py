from __future__ import annotations

from types import SimpleNamespace

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
