import asyncio
from pathlib import Path
from typing import Any

import pytest

from saki_executor.cache.asset_cache import AssetCache
from saki_executor.grpc_gen import runtime_control_pb2 as pb
from saki_executor.jobs.manager import JobManager
from saki_executor.plugins.base import ExecutorPlugin, TrainOutput
from saki_executor.plugins.registry import PluginRegistry


class _ModeAwarePlugin(ExecutorPlugin):
    def __init__(self) -> None:
        self.prepare_samples_count = 0
        self.prepare_annotations_count = 0
        self.predict_calls = 0

    @property
    def plugin_id(self) -> str:
        return "mode_aware_plugin"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def supported_job_types(self) -> list[str]:
        return ["train_detection"]

    @property
    def supported_strategies(self) -> list[str]:
        return ["uncertainty_1_minus_max_conf"]

    def validate_params(self, params: dict[str, Any]) -> None:
        del params
        return

    async def prepare_data(
            self,
            workspace,
            labels: list[dict[str, Any]],
            samples: list[dict[str, Any]],
            annotations: list[dict[str, Any]],
    ) -> None:
        del workspace, labels
        self.prepare_samples_count = len(samples)
        self.prepare_annotations_count = len(annotations)

    async def train(
            self,
            workspace,
            params: dict[str, Any],
            emit,
    ) -> TrainOutput:
        del workspace, params
        await emit("metric", {"step": 1, "epoch": 1, "metrics": {"loss": 0.1}})
        return TrainOutput(metrics={"loss": 0.1}, artifacts=[])

    async def predict_unlabeled(
            self,
            workspace,
            unlabeled_samples: list[dict[str, Any]],
            strategy: str,
            params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        del workspace, strategy, params
        self.predict_calls += 1
        return [
            {
                "sample_id": str(item.get("id") or ""),
                "score": 0.8,
                "reason": {"mock": 1.0},
            }
            for item in unlabeled_samples
            if item.get("id")
        ]

    async def stop(self, job_id: str) -> None:
        del job_id
        return


def _build_manager(tmp_path: Path, plugin: ExecutorPlugin) -> JobManager:
    registry = PluginRegistry()
    registry.register(plugin)
    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=1024 * 1024)
    manager = JobManager(runs_dir=str(tmp_path / "runs"), cache=cache, plugin_registry=registry)
    return manager


def _build_data_response_message(
        *,
        request_id: str,
        reply_to: str,
        job_id: str,
        query_type: int,
        items: list[pb.DataItem],
) -> pb.RuntimeMessage:
    return pb.RuntimeMessage(
        data_response=pb.DataResponse(
            request_id=request_id,
            reply_to=reply_to,
            job_id=job_id,
            query_type=query_type,
            items=items,
            next_cursor="",
        )
    )


def _mock_data_items(query_type: int) -> list[pb.DataItem]:
    if query_type == pb.SAMPLES:
        return [
            pb.DataItem(sample_item=pb.SampleItem(id="s1")),
            pb.DataItem(sample_item=pb.SampleItem(id="s2")),
            pb.DataItem(sample_item=pb.SampleItem(id="s3")),
            pb.DataItem(sample_item=pb.SampleItem(id="s4")),
        ]
    if query_type == pb.ANNOTATIONS:
        return [
            pb.DataItem(annotation_item=pb.AnnotationItem(id="a1", sample_id="s1", category_id="c1")),
            pb.DataItem(annotation_item=pb.AnnotationItem(id="a2", sample_id="s2", category_id="c1")),
        ]
    if query_type == pb.UNLABELED_SAMPLES:
        return [
            pb.DataItem(sample_item=pb.SampleItem(id="u1")),
            pb.DataItem(sample_item=pb.SampleItem(id="u2")),
        ]
    return []


@pytest.mark.anyio
async def test_simulation_mode_skips_topk_and_uses_ratio_subset(tmp_path: Path):
    plugin = _ModeAwarePlugin()
    manager = _build_manager(tmp_path, plugin)
    sent_messages: list[pb.RuntimeMessage] = []

    async def fake_send(message: pb.RuntimeMessage) -> None:
        sent_messages.append(message)

    async def fake_request(message: pb.RuntimeMessage) -> pb.RuntimeMessage:
        payload_type = message.WhichOneof("payload")
        assert payload_type == "data_request"
        request = message.data_request
        return _build_data_response_message(
            request_id=f"resp-{request.request_id}",
            reply_to=request.request_id,
            job_id=request.job_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_job(
        "assign-simulation-1",
        {
            "job_id": "job-sim-1",
            "project_id": "project-1",
            "source_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "simulation",
            "query_strategy": "uncertainty_1_minus_max_conf",
            "params": {
                "_iteration": 1,
                "simulation_ratio_schedule": [0.5, 1.0],
            },
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "job_result"]
    assert len(result_messages) == 1
    result = result_messages[0].job_result
    assert result.status == pb.SUCCEEDED
    assert len(result.candidates) == 0
    assert plugin.predict_calls == 0
    assert plugin.prepare_samples_count == 1
    assert plugin.prepare_annotations_count == 1


@pytest.mark.anyio
async def test_active_learning_mode_keeps_topk_sampling(tmp_path: Path):
    plugin = _ModeAwarePlugin()
    manager = _build_manager(tmp_path, plugin)
    sent_messages: list[pb.RuntimeMessage] = []

    async def fake_send(message: pb.RuntimeMessage) -> None:
        sent_messages.append(message)

    async def fake_request(message: pb.RuntimeMessage) -> pb.RuntimeMessage:
        payload_type = message.WhichOneof("payload")
        assert payload_type == "data_request"
        request = message.data_request
        return _build_data_response_message(
            request_id=f"resp-{request.request_id}",
            reply_to=request.request_id,
            job_id=request.job_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_job(
        "assign-al-1",
        {
            "job_id": "job-al-1",
            "project_id": "project-1",
            "source_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "query_strategy": "uncertainty_1_minus_max_conf",
            "params": {"topk": 10},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "job_result"]
    assert len(result_messages) == 1
    result = result_messages[0].job_result
    assert result.status == pb.SUCCEEDED
    assert len(result.candidates) == 2
    assert plugin.predict_calls == 1
    assert plugin.prepare_samples_count == 4
    assert plugin.prepare_annotations_count == 2
