from __future__ import annotations

import asyncio

import pytest

from saki_executor.cache.asset_cache import AssetCache
from saki_executor.steps.contracts import StepExecutionRequest
from saki_executor.steps.orchestration.training_data_service import TrainingDataService


@pytest.mark.anyio
async def test_prepare_filters_unconfirmed_model_annotations(tmp_path):
    async def fetch_all(step_id: str, query_type: str, project_id: str, commit_id: str):
        del step_id, project_id, commit_id
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

    request = StepExecutionRequest(
        step_id="step-1",
        round_id="round-1",
        step_type="train",
        dispatch_kind="orchestrator",
        plugin_id="plugin-a",
        resolved_params={"split_seed": 0, "plugin": {"val_split_ratio": 0.2}},
        project_id="project-1",
        input_commit_id="commit-1",
        query_strategy=None,
        mode="active_learning",
        round_index=1,
        attempt=1,
        depends_on_step_ids=[],
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

    bundle = await service.prepare(
        request=request,
        plugin=object(),
        emit=emit,
    )

    assert len(bundle.train_annotations) == 1
    assert bundle.train_annotations[0]["id"] == "ann-confirmed"
    assert bundle.train_annotations[0]["source"] == "confirmed_model"
    assert all(str(item.get("source") or "").lower() != "model" for item in bundle.train_annotations)
