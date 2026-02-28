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


class _InProcessProxy(ExecutorPlugin):
    def __init__(self, *, metadata_plugin: ExecutorPlugin, step_id: str, emit, **_kwargs):
        del step_id
        self._plugin = metadata_plugin
        self._emit = emit

    @property
    def plugin_id(self) -> str:
        return self._plugin.plugin_id

    @property
    def version(self) -> str:
        return self._plugin.version

    @property
    def supported_step_types(self) -> list[str]:
        return self._plugin.supported_step_types

    @property
    def supported_strategies(self) -> list[str]:
        return self._plugin.supported_strategies

    def validate_params(self, params: dict[str, Any]) -> None:
        self._plugin.validate_params(params)

    async def prepare_data(
            self,
            workspace,
            labels: list[dict[str, Any]],
            samples: list[dict[str, Any]],
            annotations: list[dict[str, Any]],
            dataset_ir,
    ) -> None:
        await self._plugin.prepare_data(workspace, labels, samples, annotations, dataset_ir)

    async def train(
            self,
            workspace,
            params: dict[str, Any],
            emit,
    ) -> TrainOutput:
        del emit
        return await self._plugin.train(workspace, params, self._emit)

    async def eval(
            self,
            workspace,
            params: dict[str, Any],
            emit,
    ) -> TrainOutput:
        del emit
        return await self._plugin.eval(workspace, params, self._emit)

    async def export(
            self,
            workspace,
            params: dict[str, Any],
            emit,
    ) -> TrainOutput:
        del emit
        return await self._plugin.export(workspace, params, self._emit)

    async def upload_artifact(
            self,
            workspace,
            params: dict[str, Any],
            emit,
    ) -> TrainOutput:
        del emit
        return await self._plugin.upload_artifact(workspace, params, self._emit)

    async def predict_unlabeled(
            self,
            workspace,
            unlabeled_samples: list[dict[str, Any]],
            strategy: str,
            params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return await self._plugin.predict_unlabeled(workspace, unlabeled_samples, strategy, params)

    async def predict_unlabeled_batch(
            self,
            workspace,
            unlabeled_samples: list[dict[str, Any]],
            strategy: str,
            params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return await self._plugin.predict_unlabeled_batch(workspace, unlabeled_samples, strategy, params)

    async def stop(self, step_id: str) -> None:
        await self._plugin.stop(step_id)

    async def shutdown(self) -> None:
        return


@pytest.fixture(autouse=True)
def _patch_subprocess_proxy(monkeypatch):
    monkeypatch.setattr("saki_executor.steps.orchestration.runner.SubprocessPluginProxy", _InProcessProxy)


class _ModeAwarePlugin(ExecutorPlugin):
    def __init__(self) -> None:
        self.prepare_samples_count = 0
        self.prepare_annotations_count = 0
        self.train_calls = 0
        self.eval_calls = 0
        self.export_calls = 0
        self.upload_artifact_calls = 0
        self.predict_calls = 0

    @property
    def plugin_id(self) -> str:
        return "mode_aware_plugin"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def supported_step_types(self) -> list[str]:
        return ["train", "score", "eval", "export", "upload_artifact", "custom"]

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
            dataset_ir,
    ) -> None:
        del workspace, labels, dataset_ir
        self.prepare_samples_count = len(samples)
        self.prepare_annotations_count = len(annotations)

    async def train(
            self,
            workspace,
            params: dict[str, Any],
            emit,
    ) -> TrainOutput:
        del workspace, params
        self.train_calls += 1
        await emit("metric", {"step": 1, "epoch": 1, "metrics": {"loss": 0.1}})
        return TrainOutput(metrics={"loss": 0.1}, artifacts=[])

    async def eval(
            self,
            workspace,
            params: dict[str, Any],
            emit,
    ) -> TrainOutput:
        del workspace, params
        self.eval_calls += 1
        await emit("metric", {"step": 1, "epoch": 1, "metrics": {"eval_loss": 0.12}})
        return TrainOutput(metrics={"eval_loss": 0.12}, artifacts=[])

    async def export(
            self,
            workspace,
            params: dict[str, Any],
            emit,
    ) -> TrainOutput:
        del workspace, params, emit
        self.export_calls += 1
        return TrainOutput(metrics={}, artifacts=[])

    async def upload_artifact(
            self,
            workspace,
            params: dict[str, Any],
            emit,
    ) -> TrainOutput:
        del workspace, params, emit
        self.upload_artifact_calls += 1
        return TrainOutput(metrics={}, artifacts=[])

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


class _CaptureModelParamsPlugin(_ModeAwarePlugin):
    def __init__(self) -> None:
        super().__init__()
        self.last_predict_params: dict[str, Any] | None = None

    async def predict_unlabeled(
            self,
            workspace,
            unlabeled_samples: list[dict[str, Any]],
            strategy: str,
            params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        self.last_predict_params = dict(params)
        return await super().predict_unlabeled(workspace, unlabeled_samples, strategy, params)


class _MinimalPlugin(ExecutorPlugin):
    def __init__(self) -> None:
        self.train_calls = 0
        self.predict_calls = 0

    @property
    def plugin_id(self) -> str:
        return "minimal_plugin"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def supported_step_types(self) -> list[str]:
        return ["train"]

    @property
    def supported_strategies(self) -> list[str]:
        return ["uncertainty_1_minus_max_conf"]

    async def train(
            self,
            workspace,
            params: dict[str, Any],
            emit,
    ) -> TrainOutput:
        del workspace, params
        self.train_calls += 1
        await emit("metric", {"step": 1, "epoch": 1, "metrics": {"loss": 0.2}})
        return TrainOutput(metrics={"loss": 0.2}, artifacts=[])

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
                "score": 0.7,
                "reason": {"minimal": 1.0},
            }
            for item in unlabeled_samples
            if item.get("id")
        ]


class _SlowTrainPlugin(ExecutorPlugin):
    @property
    def plugin_id(self) -> str:
        return "slow_train_plugin"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def supported_step_types(self) -> list[str]:
        return ["train", "eval"]

    @property
    def supported_strategies(self) -> list[str]:
        return ["uncertainty_1_minus_max_conf"]

    async def train(
            self,
            workspace,
            params: dict[str, Any],
            emit,
    ) -> TrainOutput:
        del workspace, params
        for index in range(1, 200):
            await asyncio.sleep(0.02)
            await emit("metric", {"step": index, "epoch": index, "metrics": {"loss": 0.5}})
        return TrainOutput(metrics={"loss": 0.5}, artifacts=[])

    async def eval(
            self,
            workspace,
            params: dict[str, Any],
            emit,
    ) -> TrainOutput:
        return await self.train(workspace, params, emit)

    async def predict_unlabeled(
            self,
            workspace,
            unlabeled_samples: list[dict[str, Any]],
            strategy: str,
            params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        del workspace, unlabeled_samples, strategy, params
        return []

    async def stop(self, step_id: str) -> None:
        del step_id
        return


def _build_manager(tmp_path: Path, plugin: ExecutorPlugin) -> StepManager:
    registry = PluginRegistry()
    registry.register(plugin)
    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=1024 * 1024)
    manager = StepManager(
        runs_dir=str(tmp_path / "runs"),
        cache=cache,
        plugin_registry=registry,
        strict_train_model_handoff=False,
    )
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
            "step_type": "train",
            "dispatch_kind": "dispatchable",
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
    assert len(result.candidates) == 0
    assert plugin.predict_calls == 0
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
            "step_type": "train",
            "dispatch_kind": "dispatchable",
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
    assert len(result.candidates) == 0
    assert plugin.predict_calls == 0
    assert plugin.prepare_samples_count == 2
    assert plugin.prepare_annotations_count == 2


@pytest.mark.anyio
async def test_startup_status_events_skip_pending(tmp_path: Path):
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
        "assign-status-seq-1",
        {
            "step_id": "task-status-seq-1",
            "round_id": "job-status-seq-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "step_type": "train",
            "dispatch_kind": "dispatchable",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    status_codes = [
        message.step_event.status_event.status
        for message in sent_messages
        if message.WhichOneof("payload") == "step_event"
        and message.step_event.WhichOneof("event_payload") == "status_event"
    ]
    assert status_codes[:2] == [pb.DISPATCHING, pb.RUNNING]
    assert pb.PENDING not in status_codes


@pytest.mark.anyio
async def test_score_step_skips_training_and_only_runs_sampling(tmp_path: Path):
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
        "assign-score-1",
        {
            "step_id": "task-score-1",
            "round_id": "job-score-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "step_type": "score",
            "dispatch_kind": "dispatchable",
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
    assert plugin.train_calls == 0
    assert plugin.predict_calls == 1


@pytest.mark.anyio
async def test_score_step_strict_model_handoff_fails_without_model_ref(tmp_path: Path):
    plugin = _ModeAwarePlugin()
    registry = PluginRegistry()
    registry.register(plugin)
    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=1024 * 1024)
    manager = StepManager(
        runs_dir=str(tmp_path / "runs"),
        cache=cache,
        plugin_registry=registry,
        strict_train_model_handoff=True,
    )
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
        "assign-score-strict-1",
        {
            "step_id": "task-score-strict-1",
            "round_id": "job-score-strict-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "step_type": "score",
            "dispatch_kind": "dispatchable",
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
    assert result.status == pb.FAILED
    assert "trained model is required" in str(result.error_message or "")


@pytest.mark.anyio
async def test_score_step_shared_model_sets_local_model_ref(tmp_path: Path):
    plugin = _CaptureModelParamsPlugin()
    manager = _build_manager(tmp_path, plugin)
    sent_messages: list[pb.RuntimeMessage] = []

    step_id = "task-score-shared-model-1"
    round_id = "job-score-shared-model-1"
    shared_model_path = (
        tmp_path
        / "runs"
        / "rounds"
        / round_id
        / "attempt_1"
        / "shared"
        / "models"
        / "best.pt"
    )
    shared_model_path.parent.mkdir(parents=True, exist_ok=True)
    shared_model_path.write_bytes(b"mock-model")

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
        "assign-score-shared-model-1",
        {
            "step_id": step_id,
            "round_id": round_id,
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "step_type": "score",
            "dispatch_kind": "dispatchable",
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

    assert plugin.last_predict_params is not None
    assert plugin.last_predict_params.get("model_source") == "custom_local"
    model_ref = str(plugin.last_predict_params.get("model_custom_ref") or "").strip()
    assert model_ref
    assert Path(model_ref).exists()


@pytest.mark.anyio
async def test_eval_step_trains_without_sampling(tmp_path: Path):
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
        "assign-eval-1",
        {
            "step_id": "task-eval-1",
            "round_id": "job-eval-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "step_type": "eval",
            "dispatch_kind": "dispatchable",
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
    assert len(result.candidates) == 0
    assert plugin.train_calls == 0
    assert plugin.eval_calls == 1
    assert plugin.predict_calls == 0


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
            "step_type": "train",
            "dispatch_kind": "dispatchable",
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
    assert len(result.candidates) == 0
    assert plugin.batch_calls == 0


@pytest.mark.anyio
async def test_orchestrator_dispatch_kind_is_rejected(tmp_path: Path):
    plugin = _ModeAwarePlugin()
    manager = _build_manager(tmp_path, plugin)
    sent_messages: list[pb.RuntimeMessage] = []
    request_calls = 0

    async def fake_send(message: pb.RuntimeMessage) -> None:
        sent_messages.append(message)

    async def fake_request(message: pb.RuntimeMessage) -> pb.RuntimeMessage:
        nonlocal request_calls
        request_calls += 1
        raise AssertionError(f"unexpected request payload: {message.WhichOneof('payload')}")

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_step(
        "assign-orchestrator-1",
        {
            "step_id": "task-orchestrator-1",
            "round_id": "job-orchestrator-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "step_type": "train",
            "dispatch_kind": "orchestrator",
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
    assert result.status == pb.FAILED
    assert "orchestrator step should not be dispatched" in result.error_message
    assert request_calls == 0


@pytest.mark.anyio
async def test_legacy_step_type_is_rejected_on_executor(tmp_path: Path):
    plugin = _ModeAwarePlugin()
    manager = _build_manager(tmp_path, plugin)
    sent_messages: list[pb.RuntimeMessage] = []
    request_calls = 0

    async def fake_send(message: pb.RuntimeMessage) -> None:
        sent_messages.append(message)

    async def fake_request(message: pb.RuntimeMessage) -> pb.RuntimeMessage:
        nonlocal request_calls
        request_calls += 1
        raise AssertionError(f"unexpected request payload: {message.WhichOneof('payload')}")

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_step(
        "assign-legacy-step-1",
        {
            "step_id": "task-legacy-step-1",
            "round_id": "job-legacy-step-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "manual",
            "step_type": "legacy_review_step",
            "dispatch_kind": "dispatchable",
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
    assert result.status == pb.FAILED
    assert "unsupported step_type for executor pipeline" in result.error_message
    assert request_calls == 0


@pytest.mark.anyio
async def test_custom_step_type_uses_train_and_sampling_pipeline(tmp_path: Path):
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
        "assign-custom-1",
        {
            "step_id": "task-custom-1",
            "round_id": "job-custom-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "step_type": "custom",
            "dispatch_kind": "dispatchable",
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
    assert plugin.train_calls == 1
    assert plugin.predict_calls == 1


@pytest.mark.anyio
async def test_plugin_default_hooks_reduce_boilerplate(tmp_path: Path):
    plugin = _MinimalPlugin()
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
        "assign-minimal-plugin-1",
        {
            "step_id": "task-minimal-plugin-1",
            "round_id": "job-minimal-plugin-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "step_type": "train",
            "dispatch_kind": "dispatchable",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {"topk": 2},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "step_result"]
    assert len(result_messages) == 1
    result = result_messages[0].step_result
    assert result.status == pb.SUCCEEDED
    assert len(result.candidates) == 0
    assert plugin.train_calls == 1
    assert plugin.predict_calls == 0


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
                "step_type": "train",
                "dispatch_kind": "dispatchable",
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


@pytest.mark.anyio
async def test_stop_step_forces_cancelled_result(tmp_path: Path):
    plugin = _SlowTrainPlugin()
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
        "assign-stop-1",
        {
            "step_id": "task-stop-1",
            "round_id": "job-stop-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "simulation",
            "step_type": "eval",
            "dispatch_kind": "dispatchable",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {},
        },
    )
    assert accepted is True
    await asyncio.sleep(0.1)
    stopped = await manager.stop_step("task-stop-1")
    assert stopped is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "step_result"]
    assert len(result_messages) == 1
    assert result_messages[0].step_result.status == pb.CANCELLED
