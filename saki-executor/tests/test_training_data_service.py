from __future__ import annotations

import asyncio

import pytest

from saki_executor.cache.asset_cache import CacheBatchResult
from saki_executor.cache.asset_cache import AssetCache
from saki_executor.steps.contracts import TaskExecutionRequest
from saki_executor.steps.orchestration.training_data_service import TrainingDataPlan, TrainingDataService
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
        execution_id="step-1",
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
        execution_id="step-1",
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
        execution_id="task-include-labels",
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
        execution_id="task-empty-filter",
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
                {"id": "sample-n1", "width": 640, "height": 480, "meta": {"_commit_review_state": "empty_confirmed"}},
                {"id": "sample-n2", "width": 640, "height": 480, "meta": {"_commit_review_state": "empty_confirmed"}},
                {"id": "sample-n3", "width": 640, "height": 480, "meta": {"_commit_review_state": "empty_confirmed"}},
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
        execution_id="task-negative-ratio-train",
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
    assert "sample-n4" not in sample_ids
    # 2 positive, ratio=1 -> keep 2 negatives
    assert len(sample_ids) == 4
    ratio_log = next((line for line in emitted_logs if "训练负样本采样完成" in line), "")
    startup_log = next((line for line in emitted_logs if "插件启动-训练负采样策略检查" in line), "")
    assert "启动=是" in startup_log
    assert "策略=按比例采样" in startup_log
    assert "negative_sample_ratio原值=1" in startup_log
    assert "negative_sample_ratio生效值=1" in startup_log
    assert "manual_negative_pool_scope=empty_confirmed_only" in startup_log
    assert "empty_confirmed_candidates=3" in startup_log
    assert "unknown_review_state_count=1" in startup_log
    assert "正样本数=2" in ratio_log
    assert "负样本候选数=3" in ratio_log
    assert "负样本保留数=2" in ratio_log
    assert "manual_negative_pool_scope=empty_confirmed_only" in ratio_log
    assert "empty_confirmed_candidates=3" in ratio_log
    assert "unknown_review_state_count=1" in ratio_log
    assert "negative_ratio=1" in ratio_log


@pytest.mark.anyio
async def test_prepare_train_negative_ratio_unlimited_keeps_all_empty_confirmed_negatives(tmp_path):
    async def fetch_all(task_id: str, query_type: str, project_id: str, commit_id: str):
        del task_id, project_id, commit_id
        if query_type == "labels":
            return [{"id": "label-a", "name": "A"}]
        if query_type == "samples":
            return [
                {"id": "sample-p1", "width": 640, "height": 480},
                {"id": "sample-n1", "width": 640, "height": 480, "meta": {"_commit_review_state": "empty_confirmed"}},
                {"id": "sample-n2", "width": 640, "height": 480},
            ]
        if query_type == "annotations":
            return [
                {"id": "ann-p1", "sample_id": "sample-p1", "category_id": "label-a", "bbox_xywh": [1, 1, 10, 10], "source": "manual"},
            ]
        return []

    request = TaskExecutionRequest(
        task_id="task-negative-ratio-unlimited",
        execution_id="task-negative-ratio-unlimited",
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

    assert {item["id"] for item in bundle.samples} == {"sample-p1", "sample-n1"}


@pytest.mark.anyio
async def test_prepare_train_negative_sampling_is_reproducible(tmp_path):
    async def fetch_all(task_id: str, query_type: str, project_id: str, commit_id: str):
        del task_id, project_id, commit_id
        if query_type == "labels":
            return [{"id": "label-a", "name": "A"}]
        if query_type == "samples":
            rows = []
            for idx in range(1, 13):
                item = {"id": f"sample-{idx}", "width": 640, "height": 480}
                if idx >= 3:
                    item["meta"] = {"_commit_review_state": "empty_confirmed"}
                rows.append(item)
            return rows
        if query_type == "annotations":
            return [
                {"id": "ann-1", "sample_id": "sample-1", "category_id": "label-a", "bbox_xywh": [1, 1, 10, 10], "source": "manual"},
                {"id": "ann-2", "sample_id": "sample-2", "category_id": "label-a", "bbox_xywh": [1, 1, 10, 10], "source": "manual"},
            ]
        return []

    request = TaskExecutionRequest(
        task_id="task-negative-ratio-repro",
        execution_id="task-negative-ratio-repro",
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
async def test_prepare_train_include_label_filter_does_not_demote_labeled_review_state_to_negative(tmp_path):
    async def fetch_all(task_id: str, query_type: str, project_id: str, commit_id: str):
        del task_id, project_id, commit_id
        if query_type == "labels":
            return [
                {"id": "label-a", "name": "A"},
                {"id": "label-b", "name": "B"},
            ]
        if query_type == "samples":
            return [
                {"id": "sample-a", "width": 640, "height": 480, "meta": {"_commit_review_state": "labeled"}},
                {"id": "sample-b", "width": 640, "height": 480, "meta": {"_commit_review_state": "labeled"}},
                {"id": "sample-c", "width": 640, "height": 480, "meta": {"_commit_review_state": "empty_confirmed"}},
            ]
        if query_type == "annotations":
            return [
                {"id": "ann-a", "sample_id": "sample-a", "category_id": "label-a", "bbox_xywh": [1, 1, 10, 10], "source": "manual"},
                {"id": "ann-b", "sample_id": "sample-b", "category_id": "label-b", "bbox_xywh": [1, 1, 10, 10], "source": "manual"},
            ]
        return []

    request = TaskExecutionRequest(
        task_id="task-label-filter-reviewed-negative-guard",
        execution_id="task-label-filter-reviewed-negative-guard",
        round_id="round-1",
        task_type="train",
        dispatch_kind="orchestrator",
        plugin_id="plugin-a",
        resolved_params={
            "training": {
                "include_label_ids": ["label-a"],
                "negative_sample_ratio": None,
            },
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

    async def emit(event_type: str, payload: dict):
        del event_type, payload

    runtime_context = TaskRuntimeContext(
        task_id="task-label-filter-reviewed-negative-guard",
        round_id="round-1",
        round_index=1,
        attempt=1,
        task_type="train",
        mode="manual",
        split_seed=13,
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
    assert sample_ids == {"sample-a", "sample-c"}
    assert "sample-b" not in sample_ids


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
        execution_id="task-negative-ratio-eval",
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


class _FakeConcurrentCache:
    def __init__(self, cache_dir: Path, *, cached_assets: set[str] | None = None, concurrency: int = 4) -> None:
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cached_assets = set(cached_assets or set())
        self.download_concurrency = concurrency
        self.calls: list[str] = []

    def is_cached(self, asset_hash: str) -> bool:
        return asset_hash in self._cached_assets

    async def ensure_cached_batch(
        self,
        items: list[tuple[str, str]],
        *,
        protected: set[str] | None = None,
        pin_task_id: str | None = None,
        progress_callback=None,
        yield_every: int = 64,
    ) -> CacheBatchResult:
        del yield_every
        paths: dict[str, Path] = {}
        cache_hits = 0
        cache_misses = 0
        for asset_hash, download_url in items:
            was_cached = self.is_cached(asset_hash)
            path = await self.ensure_cached(
                asset_hash,
                download_url,
                protected=protected,
                pin_task_id=pin_task_id,
                progress_callback=progress_callback,
            )
            paths[asset_hash] = path
            if was_cached:
                cache_hits += 1
            else:
                cache_misses += 1
        return CacheBatchResult(
            paths=paths,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            lookup_sec=0.0,
            flush_sec=0.0,
            dirty_entries=len(paths),
            flush_count=1 if paths else 0,
        )

    async def ensure_cached(
        self,
        asset_hash: str,
        download_url: str,
        *,
        protected: set[str] | None = None,
        pin_task_id: str | None = None,
        progress_callback=None,
    ) -> Path:
        del download_url, protected, pin_task_id
        self.calls.append(asset_hash)
        path = self._cache_dir / asset_hash
        if self.is_cached(asset_hash):
            path.write_bytes(b"cached")
            if progress_callback is not None:
                progress_callback({"event": "cache_hit", "asset_hash": asset_hash, "size": len(b"cached")})
            return path

        if progress_callback is not None:
            progress_callback({"event": "download_started", "asset_hash": asset_hash})
        for _ in range(3):
            await asyncio.sleep(0.45)
            if progress_callback is not None:
                progress_callback(
                    {
                        "event": "download_progress",
                        "asset_hash": asset_hash,
                        "bytes_delta": 1024,
                    }
                )
        path.write_bytes(b"downloaded")
        if progress_callback is not None:
            progress_callback({"event": "download_completed", "asset_hash": asset_hash, "size": len(b"downloaded")})
        return path


@pytest.mark.anyio
async def test_prepare_prefetches_assets_concurrently_and_emits_progress_logs(tmp_path, monkeypatch):
    monkeypatch.setattr("saki_executor.steps.orchestration.training_data_service.settings.ASSET_DOWNLOAD_PROGRESS_INTERVAL_SEC", 1)
    monkeypatch.setattr("saki_executor.steps.orchestration.training_data_service.settings.ASSET_DOWNLOAD_PROGRESS_MIN_FILE_DELTA", 1)

    async def fetch_all(task_id: str, query_type: str, project_id: str, commit_id: str):
        del task_id, project_id, commit_id
        if query_type == "labels":
            return [{"id": "label-a", "name": "A"}]
        if query_type == "samples":
            return [
                {
                    "id": "sample-a",
                    "width": 640,
                    "height": 480,
                    "asset_hash": "hash-remote-a",
                    "download_url": "https://example.test/a",
                },
                {
                    "id": "sample-b",
                    "width": 640,
                    "height": 480,
                    "asset_hash": "hash-remote-a",
                    "download_url": "https://example.test/a",
                },
                {
                    "id": "sample-c",
                    "width": 640,
                    "height": 480,
                    "asset_hash": "hash-cached-c",
                    "download_url": "https://example.test/c",
                },
                {
                    "id": "sample-d",
                    "width": 640,
                    "height": 480,
                    "asset_hash": "hash-remote-d",
                    "download_url": "https://example.test/d",
                },
            ]
        if query_type == "annotations":
            return [
                {"id": "ann-a", "sample_id": "sample-a", "category_id": "label-a", "bbox_xywh": [1, 1, 10, 10], "source": "manual"},
                {"id": "ann-b", "sample_id": "sample-b", "category_id": "label-a", "bbox_xywh": [1, 1, 10, 10], "source": "manual"},
                {"id": "ann-c", "sample_id": "sample-c", "category_id": "label-a", "bbox_xywh": [1, 1, 10, 10], "source": "manual"},
                {"id": "ann-d", "sample_id": "sample-d", "category_id": "label-a", "bbox_xywh": [1, 1, 10, 10], "source": "manual"},
            ]
        return []

    request = TaskExecutionRequest(
        task_id="task-download-progress",
        execution_id="task-download-progress",
        round_id="round-1",
        task_type="train",
        dispatch_kind="orchestrator",
        plugin_id="plugin-a",
        resolved_params={},
        project_id="project-1",
        input_commit_id="commit-1",
        query_strategy=None,
        mode="manual",
        round_index=1,
        attempt=1,
        depends_on_task_ids=[],
        raw_payload={},
    )
    cache = _FakeConcurrentCache(tmp_path / "cache", cached_assets={"hash-cached-c"}, concurrency=4)
    service = TrainingDataService(fetch_all=fetch_all, cache=cache, stop_event=asyncio.Event())
    logs: list[dict[str, object]] = []

    async def emit(event_type: str, payload: dict):
        if event_type == "log":
            logs.append(dict(payload))

    runtime_context = TaskRuntimeContext(
        task_id="task-download-progress",
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
    bundle = await service.prepare(
        request=request,
        plugin_params={"val_split_ratio": 0.2},
        runtime_context=runtime_context,
        emit=emit,
    )

    assert cache.calls.count("hash-remote-a") == 1
    assert cache.calls.count("hash-cached-c") == 1
    assert cache.calls.count("hash-remote-d") == 1
    assert {item["id"] for item in bundle.samples} == {"sample-a", "sample-b", "sample-c", "sample-d"}
    assert all(item.get("local_path") for item in bundle.samples)

    progress_logs = [item for item in logs if item.get("message_key") == "asset.download.progress"]
    assert any("训练资产下载开始" in str(item.get("message") or "") for item in progress_logs)
    assert any("训练资产下载进度" in str(item.get("message") or "") for item in progress_logs)
    assert any("训练资产下载完成" in str(item.get("message") or "") for item in progress_logs)


def test_prepared_data_cache_fingerprint_ignores_attempt(tmp_path):
    async def fetch_all(task_id: str, query_type: str, project_id: str, commit_id: str):
        del task_id, query_type, project_id, commit_id
        return []

    service = TrainingDataService(
        fetch_all=fetch_all,
        cache=AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=10 * 1024 * 1024),
        stop_event=asyncio.Event(),
    )
    plan = TrainingDataPlan(
        labels=[{"id": "label-a", "name": "A", "color": "#fff"}],
        samples=[
            {
                "id": "sample-a",
                "asset_hash": "hash-a",
                "width": 640,
                "height": 480,
                "_split": "train",
                "_split_source": "snapshot",
                "meta": {"_snapshot_partition": "seed"},
            }
        ],
        train_annotations=[
            {
                "id": "ann-a",
                "sample_id": "sample-a",
                "category_id": "label-a",
                "bbox_xywh": [1, 2, 3, 4],
                "source": "manual",
            }
        ],
        splits={"train": [{"id": "sample-a"}], "val": []},
        split_seed=11,
        val_ratio=0.2,
    )
    runtime_context = TaskRuntimeContext(
        task_id="task-a",
        round_id="round-1",
        round_index=1,
        attempt=1,
        task_type="train",
        mode="simulation",
        split_seed=11,
        train_seed=12,
        sampling_seed=13,
        resolved_device_backend="cpu",
    )
    request_a = TaskExecutionRequest(
        task_id="task-a",
        execution_id="exec-a",
        round_id="round-1",
        task_type="train",
        dispatch_kind="dispatchable",
        plugin_id="plugin-a",
        resolved_params={},
        project_id="project-1",
        input_commit_id="commit-1",
        query_strategy=None,
        mode="simulation",
        round_index=1,
        attempt=1,
        depends_on_task_ids=[],
        raw_payload={},
    )
    request_b = TaskExecutionRequest(
        task_id="task-b",
        execution_id="exec-b",
        round_id="round-1",
        task_type="train",
        dispatch_kind="dispatchable",
        plugin_id="plugin-a",
        resolved_params={},
        project_id="project-1",
        input_commit_id="commit-1",
        query_strategy=None,
        mode="simulation",
        round_index=1,
        attempt=9,
        depends_on_task_ids=[],
        raw_payload={},
    )

    fingerprint_a = service.build_prepared_data_cache_fingerprint(
        request=request_a,
        plugin_params={"imgsz": 640, "epochs": 50},
        runtime_context=runtime_context,
        plan=plan,
    )
    fingerprint_b = service.build_prepared_data_cache_fingerprint(
        request=request_b,
        plugin_params={"imgsz": 640, "epochs": 50},
        runtime_context=runtime_context,
        plan=plan,
    )

    assert fingerprint_a == fingerprint_b
