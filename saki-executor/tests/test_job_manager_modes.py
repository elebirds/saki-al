import asyncio
from pathlib import Path
from typing import Any

import pytest

from saki_executor.cache.asset_cache import AssetCache
from saki_executor.grpc_gen import runtime_control_pb2 as pb
from saki_executor.steps.manager import StepManager
from saki_executor.plugins.base import ExecutorPlugin, TrainOutput
from saki_executor.plugins.registry import PluginRegistry
from runtime_data_test_helper import build_data_response_message


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
    def supported_step_types(self) -> list[str]:
        return ["train"]

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

    async def stop(self, step_id: str) -> None:
        del step_id
        return


class _BatchScoringPlugin(_ModeAwarePlugin):
    def __init__(self) -> None:
        super().__init__()
        self.batch_calls = 0

    async def predict_unlabeled_batch(
            self,
            workspace,
            unlabeled_samples: list[dict[str, Any]],
            strategy: str,
            params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        del workspace, strategy, params
        self.batch_calls += 1
        candidates: list[dict[str, Any]] = []
        for sample in unlabeled_samples:
            sample_id = str(sample.get("id") or "")
            if not sample_id:
                continue
            score = float(sample_id.replace("u", ""))
            candidates.append({"sample_id": sample_id, "score": score, "reason": {"s": score}})
        return candidates


def _build_manager(tmp_path: Path, plugin: ExecutorPlugin) -> StepManager:
    registry = PluginRegistry()
    registry.register(plugin)
    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=1024 * 1024)
    manager = StepManager(runs_dir=str(tmp_path / "runs"), cache=cache, plugin_registry=registry)
    return manager


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
async def test_simulation_mode_keeps_topk_sampling_and_uses_labeled_subset(tmp_path: Path):
    plugin = _ModeAwarePlugin()
    manager = _build_manager(tmp_path, plugin)
    sent_messages: list[pb.RuntimeMessage] = []

    async def fake_send(message: pb.RuntimeMessage) -> None:
        sent_messages.append(message)

    async def fake_request(message: pb.RuntimeMessage) -> pb.RuntimeMessage:
        payload_type = message.WhichOneof("payload")
        assert payload_type == "data_request"
        request = message.data_request
        return build_data_response_message(
            request_id=f"resp-{request.request_id}",
            reply_to=request.request_id,
            step_id=request.step_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_step(
        "assign-simulation-1",
        {
            "step_id": "task-sim-1",
            "round_id": "job-sim-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "simulation",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "step_result"]
    assert len(result_messages) == 1
    result = result_messages[0].step_result
    assert result.status == pb.SUCCEEDED
    assert len(result.candidates) == 2
    assert plugin.predict_calls == 1
    assert plugin.prepare_samples_count == 2
    assert plugin.prepare_annotations_count == 2


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
        return build_data_response_message(
            request_id=f"resp-{request.request_id}",
            reply_to=request.request_id,
            step_id=request.step_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_step(
        "assign-al-1",
        {
            "step_id": "task-al-1",
            "round_id": "job-al-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {"topk": 10},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "step_result"]
    assert len(result_messages) == 1
    result = result_messages[0].step_result
    assert result.status == pb.SUCCEEDED
    assert len(result.candidates) == 2
    assert plugin.predict_calls == 1
    assert plugin.prepare_samples_count == 2
    assert plugin.prepare_annotations_count == 2


@pytest.mark.anyio
async def test_active_learning_streaming_topk_across_pages(tmp_path: Path):
    plugin = _BatchScoringPlugin()
    manager = _build_manager(tmp_path, plugin)
    sent_messages: list[pb.RuntimeMessage] = []

    async def fake_send(message: pb.RuntimeMessage) -> None:
        sent_messages.append(message)

    async def fake_request(message: pb.RuntimeMessage) -> pb.RuntimeMessage:
        payload_type = message.WhichOneof("payload")
        assert payload_type == "data_request"
        request = message.data_request

        next_cursor = ""
        if request.query_type == pb.UNLABELED_SAMPLES:
            if not request.cursor:
                items = [
                    pb.DataItem(sample_item=pb.SampleItem(id="u1")),
                    pb.DataItem(sample_item=pb.SampleItem(id="u5")),
                    pb.DataItem(sample_item=pb.SampleItem(id="u3")),
                ]
                next_cursor = "page-2"
            else:
                items = [
                    pb.DataItem(sample_item=pb.SampleItem(id="u2")),
                    pb.DataItem(sample_item=pb.SampleItem(id="u9")),
                    pb.DataItem(sample_item=pb.SampleItem(id="u4")),
                ]
                next_cursor = ""
            return pb.RuntimeMessage(
                data_response=build_data_response_message(
                    request_id=f"resp-{request.request_id}",
                    reply_to=request.request_id,
                    step_id=request.step_id,
                    query_type=request.query_type,
                    items=items,
                    next_cursor=next_cursor,
                ).data_response
            )

        return build_data_response_message(
            request_id=f"resp-{request.request_id}",
            reply_to=request.request_id,
            step_id=request.step_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_step(
        "assign-al-stream-1",
        {
            "step_id": "task-al-stream-1",
            "round_id": "job-al-stream-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {"topk": 2, "unlabeled_page_size": 3},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "step_result"]
    assert len(result_messages) == 1
    result = result_messages[0].step_result
    assert result.status == pb.SUCCEEDED
    assert [item.sample_id for item in result.candidates] == ["u9", "u5"]
    assert plugin.batch_calls == 2


@pytest.mark.anyio
async def test_unknown_mode_fails_with_controlled_error(tmp_path: Path):
    plugin = _ModeAwarePlugin()
    manager = _build_manager(tmp_path, plugin)
    sent_messages: list[pb.RuntimeMessage] = []
    request_calls = 0

    async def fake_send(message: pb.RuntimeMessage) -> None:
        sent_messages.append(message)

    async def fake_request(message: pb.RuntimeMessage) -> pb.RuntimeMessage:
        nonlocal request_calls
        request_calls += 1
        payload_type = message.WhichOneof("payload")
        assert payload_type == "data_request"
        request = message.data_request
        return build_data_response_message(
            request_id=f"resp-{request.request_id}",
            reply_to=request.request_id,
            step_id=request.step_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)

    with pytest.raises(ValueError, match="unsupported mode"):
        await manager.assign_step(
            "assign-unknown-mode-1",
            {
                "step_id": "task-unknown-mode-1",
                "round_id": "job-unknown-mode-1",
                "project_id": "project-1",
                "input_commit_id": "commit-1",
                "plugin_id": plugin.plugin_id,
                "mode": "unexpected_mode",
                "round_index": 1,
                "query_strategy": "uncertainty_1_minus_max_conf",
                "resolved_params": {},
            },
        )

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "step_result"]
    assert len(result_messages) == 0
    assert request_calls == 0
    assert plugin.prepare_samples_count == 0
    assert plugin.predict_calls == 0
