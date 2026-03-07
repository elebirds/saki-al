from __future__ import annotations

import asyncio

import pytest

from saki_executor.cache.asset_cache import AssetCache
from saki_executor.steps.contracts import TaskExecutionRequest
from saki_executor.steps.orchestration.training_data_service import TrainingDataService
from saki_plugin_sdk import TaskRuntimeContext


@pytest.mark.anyio
async def test_prepare_filters_unconfirmed_model_annotations(tmp_path):
    async def fetch_all(task_id: str, query_type: str, project_id: str, commit_id: str):
        del task_id, project_id, commit_id
        if query_type == "labels":
            return [{"id": "label-1", "name": "ship"}]
        if query_type == "samples":
            return [{"id": "sample-1", "width": 640, "height": 480}]
        if query_type == "annotations":
            return [
                {
                    "id": "ann-model",
                    "sample_id": "sample-1",
                    "category_id": "label-1",
                    "bbox_xywh": [10.0, 10.0, 50.0, 40.0],
                    "source": "model",
                },
                {
                    "id": "ann-confirmed",
                    "sample_id": "sample-1",
                    "category_id": "label-1",
                    "bbox_xywh": [11.0, 11.0, 40.0, 30.0],
                    "source": "confirmed_model",
                },
            ]
        return []

    request = TaskExecutionRequest(
        task_id="step-1",
        round_id="round-1",
        task_type="train",
        dispatch_kind="orchestrator",
        plugin_id="plugin-a",
        resolved_params={"split_seed": 99, "plugin": {"val_split_ratio": 0.49}},
        project_id="project-1",
        input_commit_id="commit-1",
        query_strategy=None,
        mode="manual",
        round_index=1,
        attempt=1,
        depends_on_task_ids=[],
        raw_payload={},
    )

    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=10 * 1024 * 1024)
    service = TrainingDataService(
        fetch_all=fetch_all,
        cache=cache,
        stop_event=asyncio.Event(),
    )

    async def emit(event_type: str, payload: dict):
        del event_type, payload

    runtime_context = TaskRuntimeContext(
        task_id="step-1",
        round_id="round-1",
        round_index=1,
        attempt=1,
        task_type="train",
        mode="manual",
        split_seed=3,
        train_seed=4,
        sampling_seed=5,
        resolved_device_backend="cpu",
    )
    bundle = await service.prepare(
        request=request,
        plugin_params={"val_split_ratio": 0.2},
        runtime_context=runtime_context,
        emit=emit,
    )

    assert len(bundle.train_annotations) == 1
    assert bundle.train_annotations[0]["id"] == "ann-confirmed"
    assert bundle.train_annotations[0]["source"] == "confirmed_model"
    assert all(str(item.get("source") or "").lower() != "model" for item in bundle.train_annotations)
    assert all(int(item.get("_split_seed") or 0) == 3 for item in bundle.samples)
    assert all(abs(float(item.get("_val_split_ratio") or 0.0) - 0.2) < 1e-9 for item in bundle.samples)
    assert set(bundle.splits.keys()) == {"train", "val"}
    assert "yolo_task" not in bundle.splits


@pytest.mark.anyio
async def test_prepare_requires_snapshot_split_hints_for_active_learning(tmp_path):
    async def fetch_all(task_id: str, query_type: str, project_id: str, commit_id: str):
        del task_id, project_id, commit_id
        if query_type == "labels":
            return [{"id": "label-1", "name": "ship"}]
        if query_type == "samples":
            return [{"id": "sample-1", "width": 640, "height": 480}]
        if query_type == "annotations":
            return [
                {
                    "id": "ann-confirmed",
                    "sample_id": "sample-1",
                    "category_id": "label-1",
                    "bbox_xywh": [11.0, 11.0, 40.0, 30.0],
                    "source": "confirmed_model",
                },
            ]
        return []

    request = TaskExecutionRequest(
        task_id="step-1",
        round_id="round-1",
        task_type="train",
        dispatch_kind="orchestrator",
        plugin_id="plugin-a",
        resolved_params={"split_seed": 99, "plugin": {"val_split_ratio": 0.49}},
        project_id="project-1",
        input_commit_id="commit-1",
        query_strategy=None,
        mode="active_learning",
        round_index=1,
        attempt=1,
        depends_on_task_ids=[],
        raw_payload={},
    )
    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=10 * 1024 * 1024)
    service = TrainingDataService(
        fetch_all=fetch_all,
        cache=cache,
        stop_event=asyncio.Event(),
    )

    async def emit(event_type: str, payload: dict):
        del event_type, payload

    runtime_context = TaskRuntimeContext(
        task_id="step-1",
        round_id="round-1",
        round_index=1,
        attempt=1,
        task_type="train",
        mode="active_learning",
        split_seed=3,
        train_seed=4,
        sampling_seed=5,
        resolved_device_backend="cpu",
    )
    with pytest.raises(RuntimeError, match="snapshot split hints"):
        await service.prepare(
            request=request,
            plugin_params={"val_split_ratio": 0.2},
            runtime_context=runtime_context,
            emit=emit,
        )


@pytest.mark.anyio
async def test_prepare_filters_training_data_by_include_label_ids(tmp_path):
    async def fetch_all(task_id: str, query_type: str, project_id: str, commit_id: str):
        del task_id, project_id, commit_id
        if query_type == "labels":
            return [
                {"id": "label-a", "name": "A"},
                {"id": "label-b", "name": "B"},
            ]
        if query_type == "samples":
            return [
                {"id": "sample-a", "width": 640, "height": 480},
                {"id": "sample-b", "width": 640, "height": 480},
            ]
        if query_type == "annotations":
            return [
                {
                    "id": "ann-a",
                    "sample_id": "sample-a",
                    "category_id": "label-a",
                    "bbox_xywh": [10.0, 10.0, 50.0, 40.0],
                    "source": "manual",
                },
                {
                    "id": "ann-b",
                    "sample_id": "sample-b",
                    "category_id": "label-b",
                    "bbox_xywh": [11.0, 11.0, 40.0, 30.0],
                    "source": "manual",
                },
            ]
        return []

    request = TaskExecutionRequest(
        task_id="task-include-labels",
        round_id="round-1",
        task_type="train",
        dispatch_kind="orchestrator",
        plugin_id="plugin-a",
        resolved_params={
            "training": {"include_label_ids": ["label-a"]},
            "plugin": {"val_split_ratio": 0.2},
        },
        project_id="project-1",
        input_commit_id="commit-1",
        query_strategy=None,
        mode="manual",
        round_index=1,
        attempt=1,
        depends_on_task_ids=[],
        raw_payload={},
    )

    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=10 * 1024 * 1024)
    service = TrainingDataService(
        fetch_all=fetch_all,
        cache=cache,
        stop_event=asyncio.Event(),
    )

    async def emit(event_type: str, payload: dict):
        del event_type, payload

    runtime_context = TaskRuntimeContext(
        task_id="task-include-labels",
        round_id="round-1",
        round_index=1,
        attempt=1,
        task_type="train",
        mode="manual",
        split_seed=3,
        train_seed=4,
        sampling_seed=5,
        resolved_device_backend="cpu",
    )
    bundle = await service.prepare(
        request=request,
        plugin_params={"val_split_ratio": 0.2},
        runtime_context=runtime_context,
        emit=emit,
    )

    assert [item["id"] for item in bundle.labels] == ["label-a"]
    assert [item["id"] for item in bundle.train_annotations] == ["ann-a"]
    assert [item["id"] for item in bundle.samples] == ["sample-a"]


@pytest.mark.anyio
async def test_prepare_fails_when_include_label_ids_yields_empty_supervised_data(tmp_path):
    async def fetch_all(task_id: str, query_type: str, project_id: str, commit_id: str):
        del task_id, project_id, commit_id
        if query_type == "labels":
            return [{"id": "label-a", "name": "A"}]
        if query_type == "samples":
            return [{"id": "sample-a", "width": 640, "height": 480}]
        if query_type == "annotations":
            return [
                {
                    "id": "ann-a",
                    "sample_id": "sample-a",
                    "category_id": "label-a",
                    "bbox_xywh": [10.0, 10.0, 50.0, 40.0],
                    "source": "manual",
                },
            ]
        return []

    request = TaskExecutionRequest(
        task_id="task-empty-filter",
        round_id="round-1",
        task_type="eval",
        dispatch_kind="orchestrator",
        plugin_id="plugin-a",
        resolved_params={
            "training": {"include_label_ids": ["label-z"]},
            "plugin": {"val_split_ratio": 0.2},
        },
        project_id="project-1",
        input_commit_id="commit-1",
        query_strategy=None,
        mode="manual",
        round_index=1,
        attempt=1,
        depends_on_task_ids=[],
        raw_payload={},
    )

    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=10 * 1024 * 1024)
    service = TrainingDataService(
        fetch_all=fetch_all,
        cache=cache,
        stop_event=asyncio.Event(),
    )

    async def emit(event_type: str, payload: dict):
        del event_type, payload

    runtime_context = TaskRuntimeContext(
        task_id="task-empty-filter",
        round_id="round-1",
        round_index=1,
        attempt=1,
        task_type="eval",
        mode="manual",
        split_seed=3,
        train_seed=4,
        sampling_seed=5,
        resolved_device_backend="cpu",
    )
    with pytest.raises(RuntimeError, match="training label filter produced empty supervised dataset"):
        await service.prepare(
            request=request,
            plugin_params={"val_split_ratio": 0.2},
            runtime_context=runtime_context,
            emit=emit,
        )


@pytest.mark.anyio
async def test_prepare_train_keeps_negative_samples_by_ratio(tmp_path):
    async def fetch_all(task_id: str, query_type: str, project_id: str, commit_id: str):
        del task_id, project_id, commit_id
        if query_type == "labels":
            return [{"id": "label-a", "name": "A"}]
        if query_type == "samples":
            return [
                {"id": "sample-p1", "width": 640, "height": 480},
                {"id": "sample-p2", "width": 640, "height": 480},
                {"id": "sample-n1", "width": 640, "height": 480},
                {"id": "sample-n2", "width": 640, "height": 480},
                {"id": "sample-n3", "width": 640, "height": 480},
                {"id": "sample-n4", "width": 640, "height": 480},
            ]
        if query_type == "annotations":
            return [
                {"id": "ann-p1", "sample_id": "sample-p1", "category_id": "label-a", "bbox_xywh": [1, 1, 10, 10], "source": "manual"},
                {"id": "ann-p2", "sample_id": "sample-p2", "category_id": "label-a", "bbox_xywh": [1, 1, 10, 10], "source": "manual"},
            ]
        return []

    request = TaskExecutionRequest(
        task_id="task-negative-ratio-train",
        round_id="round-1",
        task_type="train",
        dispatch_kind="orchestrator",
        plugin_id="plugin-a",
        resolved_params={
            "training": {"negative_sample_ratio": 1},
        },
        project_id="project-1",
        input_commit_id="commit-1",
        query_strategy=None,
        mode="manual",
        round_index=1,
        attempt=1,
        depends_on_task_ids=[],
        raw_payload={},
    )

    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=10 * 1024 * 1024)
    service = TrainingDataService(fetch_all=fetch_all, cache=cache, stop_event=asyncio.Event())
    emitted_logs: list[str] = []

    async def emit(event_type: str, payload: dict):
        if event_type == "log":
            emitted_logs.append(str(payload.get("message") or ""))

    runtime_context = TaskRuntimeContext(
        task_id="task-negative-ratio-train",
        round_id="round-1",
        round_index=1,
        attempt=1,
        task_type="train",
        mode="manual",
        split_seed=17,
        train_seed=4,
        sampling_seed=5,
        resolved_device_backend="cpu",
    )
    bundle = await service.prepare(
        request=request,
        plugin_params={"val_split_ratio": 0.2},
        runtime_context=runtime_context,
        emit=emit,
    )

    sample_ids = {item["id"] for item in bundle.samples}
    assert {"sample-p1", "sample-p2"}.issubset(sample_ids)
    # 2 positive, ratio=1 -> keep 2 negatives
    assert len(sample_ids) == 4
    ratio_log = next((line for line in emitted_logs if "训练负样本采样完成" in line), "")
    assert "positive_samples=2" in ratio_log
    assert "negative_candidates=4" in ratio_log
    assert "negative_kept=2" in ratio_log
    assert "negative_ratio=1" in ratio_log


@pytest.mark.anyio
async def test_prepare_train_negative_ratio_unlimited_keeps_all_negatives(tmp_path):
    async def fetch_all(task_id: str, query_type: str, project_id: str, commit_id: str):
        del task_id, project_id, commit_id
        if query_type == "labels":
            return [{"id": "label-a", "name": "A"}]
        if query_type == "samples":
            return [
                {"id": "sample-p1", "width": 640, "height": 480},
                {"id": "sample-n1", "width": 640, "height": 480},
                {"id": "sample-n2", "width": 640, "height": 480},
            ]
        if query_type == "annotations":
            return [
                {"id": "ann-p1", "sample_id": "sample-p1", "category_id": "label-a", "bbox_xywh": [1, 1, 10, 10], "source": "manual"},
            ]
        return []

    request = TaskExecutionRequest(
        task_id="task-negative-ratio-unlimited",
        round_id="round-1",
        task_type="train",
        dispatch_kind="orchestrator",
        plugin_id="plugin-a",
        resolved_params={"training": {"negative_sample_ratio": None}},
        project_id="project-1",
        input_commit_id="commit-1",
        query_strategy=None,
        mode="manual",
        round_index=1,
        attempt=1,
        depends_on_task_ids=[],
        raw_payload={},
    )

    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=10 * 1024 * 1024)
    service = TrainingDataService(fetch_all=fetch_all, cache=cache, stop_event=asyncio.Event())

    async def emit(event_type: str, payload: dict):
        del event_type, payload

    runtime_context = TaskRuntimeContext(
        task_id="task-negative-ratio-unlimited",
        round_id="round-1",
        round_index=1,
        attempt=1,
        task_type="train",
        mode="manual",
        split_seed=17,
        train_seed=4,
        sampling_seed=5,
        resolved_device_backend="cpu",
    )
    bundle = await service.prepare(
        request=request,
        plugin_params={"val_split_ratio": 0.2},
        runtime_context=runtime_context,
        emit=emit,
    )

    assert {item["id"] for item in bundle.samples} == {"sample-p1", "sample-n1", "sample-n2"}


@pytest.mark.anyio
async def test_prepare_train_negative_sampling_is_reproducible(tmp_path):
    async def fetch_all(task_id: str, query_type: str, project_id: str, commit_id: str):
        del task_id, project_id, commit_id
        if query_type == "labels":
            return [{"id": "label-a", "name": "A"}]
        if query_type == "samples":
            return [
                {"id": f"sample-{idx}", "width": 640, "height": 480}
                for idx in range(1, 13)
            ]
        if query_type == "annotations":
            return [
                {"id": "ann-1", "sample_id": "sample-1", "category_id": "label-a", "bbox_xywh": [1, 1, 10, 10], "source": "manual"},
                {"id": "ann-2", "sample_id": "sample-2", "category_id": "label-a", "bbox_xywh": [1, 1, 10, 10], "source": "manual"},
            ]
        return []

    request = TaskExecutionRequest(
        task_id="task-negative-ratio-repro",
        round_id="round-1",
        task_type="train",
        dispatch_kind="orchestrator",
        plugin_id="plugin-a",
        resolved_params={"training": {"negative_sample_ratio": 2}},
        project_id="project-1",
        input_commit_id="commit-1",
        query_strategy=None,
        mode="manual",
        round_index=1,
        attempt=1,
        depends_on_task_ids=[],
        raw_payload={},
    )
    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=10 * 1024 * 1024)
    service = TrainingDataService(fetch_all=fetch_all, cache=cache, stop_event=asyncio.Event())

    async def emit(event_type: str, payload: dict):
        del event_type, payload

    runtime_context = TaskRuntimeContext(
        task_id="task-negative-ratio-repro",
        round_id="round-1",
        round_index=1,
        attempt=1,
        task_type="train",
        mode="manual",
        split_seed=11,
        train_seed=4,
        sampling_seed=5,
        resolved_device_backend="cpu",
    )
    bundle_1 = await service.prepare(
        request=request,
        plugin_params={"val_split_ratio": 0.2},
        runtime_context=runtime_context,
        emit=emit,
    )
    bundle_2 = await service.prepare(
        request=request,
        plugin_params={"val_split_ratio": 0.2},
        runtime_context=runtime_context,
        emit=emit,
    )
    ids_1 = sorted(item["id"] for item in bundle_1.samples)
    ids_2 = sorted(item["id"] for item in bundle_2.samples)
    assert ids_1 == ids_2


@pytest.mark.anyio
async def test_prepare_eval_ignores_negative_ratio_and_keeps_all_negatives(tmp_path):
    async def fetch_all(task_id: str, query_type: str, project_id: str, commit_id: str):
        del task_id, project_id, commit_id
        if query_type == "labels":
            return [{"id": "label-a", "name": "A"}]
        if query_type == "samples":
            return [
                {"id": "sample-p1", "width": 640, "height": 480},
                {"id": "sample-n1", "width": 640, "height": 480},
                {"id": "sample-n2", "width": 640, "height": 480},
            ]
        if query_type == "annotations":
            return [
                {"id": "ann-p1", "sample_id": "sample-p1", "category_id": "label-a", "bbox_xywh": [1, 1, 10, 10], "source": "manual"},
            ]
        return []

    request = TaskExecutionRequest(
        task_id="task-negative-ratio-eval",
        round_id="round-1",
        task_type="eval",
        dispatch_kind="orchestrator",
        plugin_id="plugin-a",
        resolved_params={"training": {"negative_sample_ratio": 0}},
        project_id="project-1",
        input_commit_id="commit-1",
        query_strategy=None,
        mode="manual",
        round_index=1,
        attempt=1,
        depends_on_task_ids=[],
        raw_payload={},
    )
    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=10 * 1024 * 1024)
    service = TrainingDataService(fetch_all=fetch_all, cache=cache, stop_event=asyncio.Event())

    async def emit(event_type: str, payload: dict):
        del event_type, payload

    runtime_context = TaskRuntimeContext(
        task_id="task-negative-ratio-eval",
        round_id="round-1",
        round_index=1,
        attempt=1,
        task_type="eval",
        mode="manual",
        split_seed=11,
        train_seed=4,
        sampling_seed=5,
        resolved_device_backend="cpu",
    )
    bundle = await service.prepare(
        request=request,
        plugin_params={"val_split_ratio": 0.2},
        runtime_context=runtime_context,
        emit=emit,
    )
    assert {item["id"] for item in bundle.samples} == {"sample-p1", "sample-n1", "sample-n2"}
