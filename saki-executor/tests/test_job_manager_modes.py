import asyncio
from pathlib import Path
from typing import Any

import pytest

from saki_executor.cache.asset_cache import AssetCache
from saki_executor.grpc_gen import runtime_control_pb2 as pb
from saki_executor.plugins.external_handle import ExternalPluginDescriptor
from saki_executor.steps.manager import TaskManager
from saki_executor.plugins.registry import PluginRegistry
from runtime_data_test_helper import build_data_response_message
from saki_plugin_sdk import ExecutionBindingContext, ExecutorPlugin, PluginManifest, TaskRuntimeContext, TrainOutput


class _InProcessProxy(ExecutorPlugin):
    def __init__(self, *, metadata_plugin: ExecutorPlugin, task_id: str, emit, **_kwargs):
        del task_id
        self._plugin = metadata_plugin
        self._emit = emit

    @property
    def plugin_id(self) -> str:
        return self._plugin.plugin_id

    @property
    def version(self) -> str:
        return self._plugin.version

    @property
    def supported_task_types(self) -> list[str]:
        return self._plugin.supported_task_types

    @property
    def supported_strategies(self) -> list[str]:
        return self._plugin.supported_strategies

    def validate_params(
        self,
        params: dict[str, Any],
        *,
        context: TaskRuntimeContext | None = None,
    ) -> None:
        self._plugin.validate_params(params, context=context)

    async def prepare_data(
            self,
            workspace,
            labels: list[dict[str, Any]],
            samples: list[dict[str, Any]],
            annotations: list[dict[str, Any]],
            dataset_ir,
            splits: dict[str, list[dict[str, Any]]] | None = None,
            *,
            context: TaskRuntimeContext,
    ) -> None:
        await self._plugin.prepare_data(
            workspace,
            labels,
            samples,
            annotations,
            dataset_ir,
            splits=splits,
            context=context,
        )

    async def train(
            self,
            workspace,
            params: dict[str, Any],
            emit,
            *,
            context: TaskRuntimeContext,
    ) -> TrainOutput:
        del emit
        return await self._plugin.train(workspace, params, self._emit, context=context)

    async def eval(
            self,
            workspace,
            params: dict[str, Any],
            emit,
            *,
            context: TaskRuntimeContext,
    ) -> TrainOutput:
        del emit
        return await self._plugin.eval(workspace, params, self._emit, context=context)

    async def predict_unlabeled(
            self,
            workspace,
            unlabeled_samples: list[dict[str, Any]],
            strategy: str,
            params: dict[str, Any],
            *,
            context: TaskRuntimeContext,
    ) -> list[dict[str, Any]]:
        return await self._plugin.predict_unlabeled(
            workspace,
            unlabeled_samples,
            strategy,
            params,
            context=context,
        )

    async def predict_unlabeled_batch(
            self,
            workspace,
            unlabeled_samples: list[dict[str, Any]],
            strategy: str,
            params: dict[str, Any],
            *,
            context: TaskRuntimeContext,
    ) -> list[dict[str, Any]]:
        return await self._plugin.predict_unlabeled_batch(
            workspace,
            unlabeled_samples,
            strategy,
            params,
            context=context,
        )

    async def stop(self, task_id: str) -> None:
        await self._plugin.stop(task_id)

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
        self.predict_calls = 0

    @property
    def plugin_id(self) -> str:
        return "mode_aware_plugin"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def supported_task_types(self) -> list[str]:
        return ["train", "score", "predict", "eval", "custom"]

    @property
    def supported_strategies(self) -> list[str]:
        return ["uncertainty_1_minus_max_conf"]

    def validate_params(self, params: dict[str, Any], *, context: TaskRuntimeContext | None = None) -> None:
        del params, context
        return

    async def prepare_data(
            self,
            workspace,
            labels: list[dict[str, Any]],
            samples: list[dict[str, Any]],
            annotations: list[dict[str, Any]],
            dataset_ir,
            splits: dict[str, list[dict[str, Any]]] | None = None,
            *,
            context: TaskRuntimeContext,
    ) -> None:
        del workspace, labels, dataset_ir, splits, context
        self.prepare_samples_count = len(samples)
        self.prepare_annotations_count = len(annotations)

    async def train(
            self,
            workspace,
            params: dict[str, Any],
            emit,
            *,
            context: TaskRuntimeContext,
    ) -> TrainOutput:
        del workspace, params, context
        self.train_calls += 1
        await emit("metric", {"step": 1, "epoch": 1, "metrics": {"loss": 0.1}})
        return TrainOutput(metrics={"loss": 0.1}, artifacts=[])

    async def eval(
            self,
            workspace,
            params: dict[str, Any],
            emit,
            *,
            context: TaskRuntimeContext,
    ) -> TrainOutput:
        del workspace, params, context
        self.eval_calls += 1
        await emit("metric", {"step": 1, "epoch": 1, "metrics": {"eval_loss": 0.12}})
        return TrainOutput(metrics={"eval_loss": 0.12}, artifacts=[])

    async def predict_unlabeled(
            self,
            workspace,
            unlabeled_samples: list[dict[str, Any]],
            strategy: str,
            params: dict[str, Any],
            *,
            context: TaskRuntimeContext,
    ) -> list[dict[str, Any]]:
        del workspace, strategy, params, context
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

    async def stop(self, task_id: str) -> None:
        del task_id
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
            *,
            context: TaskRuntimeContext,
    ) -> list[dict[str, Any]]:
        del workspace, strategy, params, context
        self.batch_calls += 1
        candidates: list[dict[str, Any]] = []
        for sample in unlabeled_samples:
            sample_id = str(sample.get("id") or "")
            if not sample_id:
                continue
            digits = "".join(ch for ch in sample_id if ch.isdigit())
            score = float(digits or 0)
            candidates.append({"sample_id": sample_id, "score": score, "reason": {"s": score}})
        return candidates


class _BatchTopKStrictPlugin(_BatchScoringPlugin):
    def __init__(self) -> None:
        super().__init__()
        self.seen_topk: list[int] = []

    async def predict_unlabeled_batch(
            self,
            workspace,
            unlabeled_samples: list[dict[str, Any]],
            strategy: str,
            params: dict[str, Any],
            *,
            context: TaskRuntimeContext,
    ) -> list[dict[str, Any]]:
        candidates = await super().predict_unlabeled_batch(
            workspace,
            unlabeled_samples,
            strategy,
            params,
            context=context,
        )
        raw_topk = params.get("topk", params.get("sampling_topk", 0))
        try:
            topk = int(raw_topk)
        except Exception:
            topk = 0
        self.seen_topk.append(topk)
        if topk <= 0:
            return []
        return candidates[:topk]


class _InvalidPredictionSnapshotPlugin(_BatchScoringPlugin):
    async def predict_unlabeled_batch(
            self,
            workspace,
            unlabeled_samples: list[dict[str, Any]],
            strategy: str,
            params: dict[str, Any],
            *,
            context: TaskRuntimeContext,
    ) -> list[dict[str, Any]]:
        candidates = await super().predict_unlabeled_batch(
            workspace,
            unlabeled_samples,
            strategy,
            params,
            context=context,
        )
        if not candidates:
            return candidates
        first = dict(candidates[0])
        first["prediction_snapshot"] = "invalid-snapshot"
        return [first, *candidates[1:]]


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
            *,
            context: TaskRuntimeContext,
    ) -> list[dict[str, Any]]:
        self.last_predict_params = dict(params)
        return await super().predict_unlabeled(
            workspace,
            unlabeled_samples,
            strategy,
            params,
            context=context,
        )


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
    def supported_task_types(self) -> list[str]:
        return ["train"]

    @property
    def supported_strategies(self) -> list[str]:
        return ["uncertainty_1_minus_max_conf"]

    async def train(
            self,
            workspace,
            params: dict[str, Any],
            emit,
            *,
            context: TaskRuntimeContext,
    ) -> TrainOutput:
        del workspace, params, context
        self.train_calls += 1
        await emit("metric", {"step": 1, "epoch": 1, "metrics": {"loss": 0.2}})
        return TrainOutput(metrics={"loss": 0.2}, artifacts=[])

    async def predict_unlabeled(
            self,
            workspace,
            unlabeled_samples: list[dict[str, Any]],
            strategy: str,
            params: dict[str, Any],
            *,
            context: TaskRuntimeContext,
    ) -> list[dict[str, Any]]:
        del workspace, strategy, params, context
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


class _ContextProbePlugin(_MinimalPlugin):
    def __init__(self) -> None:
        super().__init__()
        self.context_ids: list[int] = []
        self.context_snapshots: list[dict[str, Any]] = []

    def _capture_context(self, context: TaskRuntimeContext | ExecutionBindingContext | None) -> None:
        if context is None:
            return
        task_context = context.task_context if isinstance(context, ExecutionBindingContext) else context
        self.context_ids.append(id(task_context))
        self.context_snapshots.append(task_context.to_dict())

    def validate_params(
        self,
        params: dict[str, Any],
        *,
        context: TaskRuntimeContext | ExecutionBindingContext | None = None,
    ) -> None:
        del params
        self._capture_context(context)

    async def prepare_data(
            self,
            workspace,
            labels: list[dict[str, Any]],
            samples: list[dict[str, Any]],
            annotations: list[dict[str, Any]],
            dataset_ir,
            splits: dict[str, list[dict[str, Any]]] | None = None,
            *,
            context: ExecutionBindingContext,
    ) -> None:
        del workspace, labels, samples, annotations, dataset_ir, splits
        self._capture_context(context)

    async def train(
            self,
            workspace,
            params: dict[str, Any],
            emit,
            *,
            context: ExecutionBindingContext,
    ) -> TrainOutput:
        self._capture_context(context)
        return await super().train(
            workspace,
            params,
            emit,
            context=context,
        )


class _SlowTrainPlugin(ExecutorPlugin):
    @property
    def plugin_id(self) -> str:
        return "slow_train_plugin"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def supported_task_types(self) -> list[str]:
        return ["train", "eval"]

    @property
    def supported_strategies(self) -> list[str]:
        return ["uncertainty_1_minus_max_conf"]

    async def train(
            self,
            workspace,
            params: dict[str, Any],
            emit,
            *,
            context: TaskRuntimeContext,
    ) -> TrainOutput:
        del workspace, params, context
        for index in range(1, 200):
            await asyncio.sleep(0.02)
            await emit("metric", {"step": index, "epoch": index, "metrics": {"loss": 0.5}})
        return TrainOutput(metrics={"loss": 0.5}, artifacts=[])

    async def eval(
            self,
            workspace,
            params: dict[str, Any],
            emit,
            *,
            context: TaskRuntimeContext,
    ) -> TrainOutput:
        return await self.train(workspace, params, emit, context=context)

    async def predict_unlabeled(
            self,
            workspace,
            unlabeled_samples: list[dict[str, Any]],
            strategy: str,
            params: dict[str, Any],
            *,
            context: TaskRuntimeContext,
    ) -> list[dict[str, Any]]:
        del workspace, unlabeled_samples, strategy, params, context
        return []

    async def stop(self, task_id: str) -> None:
        del task_id
        return


def _build_manager(tmp_path: Path, plugin: ExecutorPlugin) -> TaskManager:
    registry = PluginRegistry()
    registry.register(plugin)
    cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=1024 * 1024)
    manager = TaskManager(
        runs_dir=str(tmp_path / "runs"),
        cache=cache,
        plugin_registry=registry,
        strict_train_model_handoff=False,
    )
    return manager


def _mock_data_items(query_type: int) -> list[pb.DataItem]:
    def _sample(sample_id: str, split: str) -> pb.DataItem:
        sample = pb.SampleItem(id=sample_id)
        sample.meta.update({"_snapshot_split": split})
        return pb.DataItem(sample_item=sample)

    if query_type == pb.SAMPLES:
        return [
            _sample("s1", "train"),
            _sample("s2", "train"),
            _sample("s3", "val"),
            _sample("s4", "val"),
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
            task_id=request.task_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_task(
        "assign-simulation-1",
        {
            "task_id": "task-sim-1",
            "round_id": "job-sim-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "simulation",
            "task_type": "train",
            "dispatch_kind": "dispatchable",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "task_result"]
    assert len(result_messages) == 1
    result = result_messages[0].task_result
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
            task_id=request.task_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_task(
        "assign-al-1",
        {
            "task_id": "task-al-1",
            "round_id": "job-al-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "task_type": "train",
            "dispatch_kind": "dispatchable",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {"topk": 10},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "task_result"]
    assert len(result_messages) == 1
    result = result_messages[0].task_result
    assert result.status == pb.SUCCEEDED
    assert len(result.candidates) == 0
    assert plugin.predict_calls == 0
    assert plugin.prepare_samples_count == 2
    assert plugin.prepare_annotations_count == 2


@pytest.mark.anyio
async def test_runtime_context_built_once_and_reused_across_step_pipeline(tmp_path: Path):
    plugin = _ContextProbePlugin()
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
            task_id=request.task_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)
    accepted = await manager.assign_task(
        "assign-context-once-1",
        {
            "task_id": "task-context-once-1",
            "round_id": "job-context-once-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "simulation",
            "task_type": "train",
            "dispatch_kind": "dispatchable",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {
                "split_seed": 17,
                "train_seed": 27,
                "sampling_seed": 37,
            },
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "task_result"]
    assert len(result_messages) == 1
    assert result_messages[0].task_result.status == pb.SUCCEEDED

    assert len(plugin.context_ids) >= 3
    assert len(set(plugin.context_ids)) == 1
    assert len(plugin.context_snapshots) == len(plugin.context_ids)
    first = plugin.context_snapshots[0]
    assert all(snapshot == first for snapshot in plugin.context_snapshots[1:])
    assert int(first.get("split_seed") or 0) == 17
    assert int(first.get("train_seed") or 0) == 27
    assert int(first.get("sampling_seed") or 0) == 37
    assert str(first.get("task_type") or "") == "train"
    assert str(first.get("mode") or "") == "simulation"


@pytest.mark.anyio
async def test_external_handle_validation_fails_before_proxy_start(tmp_path: Path, monkeypatch):
    proxy_started = False

    class _FailIfProxyBuilt:
        def __init__(self, *args, **kwargs):
            nonlocal proxy_started
            proxy_started = True
            raise AssertionError("proxy should not be built when host validation fails")

    monkeypatch.setattr("saki_executor.steps.orchestration.runner.SubprocessPluginProxy", _FailIfProxyBuilt)

    manifest = PluginManifest.model_validate(
        {
            "plugin_id": "strict_external_plugin",
            "version": "2.0.0",
            "display_name": "Strict External Plugin",
            "supported_task_types": ["train"],
            "supported_strategies": ["uncertainty_1_minus_max_conf"],
            "runtime_profiles": [
                {
                    "id": "cpu",
                    "priority": 100,
                    "when": "host.backends.includes('cpu')",
                    "dependency_groups": ["profile-cpu"],
                    "allowed_backends": ["cpu"],
                }
            ],
            "config_schema": {
                "title": "Strict Config",
                "fields": [
                    {"key": "epochs", "label": "Epochs", "type": "integer", "required": True, "min": 1},
                ],
            },
            "entrypoint": "dummy.worker:main",
        }
    )
    plugin_dir = tmp_path / "strict_external_plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    handle = ExternalPluginDescriptor(
        manifest=manifest,
        plugin_dir=plugin_dir,
        python_path=Path(__file__),
    )
    registry = PluginRegistry()
    registry.register(handle)
    manager = TaskManager(
        runs_dir=str(tmp_path / "runs"),
        cache=AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=1024 * 1024),
        plugin_registry=registry,
        strict_train_model_handoff=False,
    )
    sent_messages: list[pb.RuntimeMessage] = []
    request_called = False

    async def fake_send(message: pb.RuntimeMessage) -> None:
        sent_messages.append(message)

    async def fake_request(message: pb.RuntimeMessage) -> pb.RuntimeMessage:
        nonlocal request_called
        request_called = True
        raise AssertionError(f"request path should not run, payload={message.WhichOneof('payload')}")

    manager.set_transport(fake_send, fake_request)
    accepted = await manager.assign_task(
        "assign-strict-external-1",
        {
            "task_id": "task-strict-external-1",
            "round_id": "job-strict-external-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": "strict_external_plugin",
            "mode": "simulation",
            "task_type": "train",
            "dispatch_kind": "dispatchable",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "task_result"]
    assert len(result_messages) == 1
    result = result_messages[0].task_result
    assert result.status == pb.FAILED
    error_message = str(result.error_message or "")
    assert "plugin_id=strict_external_plugin task_id=task-strict-external-1" in error_message
    assert "required" in error_message
    assert proxy_started is False
    assert request_called is False


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
            task_id=request.task_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_task(
        "assign-status-seq-1",
        {
            "task_id": "task-status-seq-1",
            "round_id": "job-status-seq-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "task_type": "train",
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
        message.task_event.status_event.status
        for message in sent_messages
        if message.WhichOneof("payload") == "task_event"
        and message.task_event.WhichOneof("event_payload") == "status_event"
    ]
    assert status_codes[:5] == [
        pb.DISPATCHING,
        pb.SYNCING_ENV,
        pb.PROBING_RUNTIME,
        pb.BINDING_DEVICE,
        pb.RUNNING,
    ]
    assert pb.PENDING not in status_codes


@pytest.mark.anyio
async def test_syncing_env_failure_stops_before_runtime_probe(tmp_path: Path, monkeypatch):
    plugin = _ModeAwarePlugin()
    manager = _build_manager(tmp_path, plugin)
    sent_messages: list[pb.RuntimeMessage] = []

    def _raise_sync(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("profile sync failed")

    monkeypatch.setattr(
        "saki_executor.steps.orchestration.runtime_binding_service.RuntimeBindingService.ensure_profile_environment",
        _raise_sync,
    )

    async def fake_send(message: pb.RuntimeMessage) -> None:
        sent_messages.append(message)

    async def fake_request(message: pb.RuntimeMessage) -> pb.RuntimeMessage:
        request = message.data_request
        return build_data_response_message(
            request_id=f"resp-{request.request_id}",
            reply_to=request.request_id,
            task_id=request.task_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)
    accepted = await manager.assign_task(
        "assign-sync-failed-1",
        {
            "task_id": "task-sync-failed-1",
            "round_id": "job-sync-failed-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "task_type": "train",
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
        message.task_event.status_event.status
        for message in sent_messages
        if message.WhichOneof("payload") == "task_event"
        and message.task_event.WhichOneof("event_payload") == "status_event"
    ]
    assert status_codes[:2] == [pb.DISPATCHING, pb.SYNCING_ENV]
    assert pb.PROBING_RUNTIME not in status_codes
    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "task_result"]
    assert len(result_messages) == 1
    assert result_messages[0].task_result.status == pb.FAILED


@pytest.mark.anyio
async def test_runtime_probe_failure_stops_before_binding(tmp_path: Path, monkeypatch):
    plugin = _ModeAwarePlugin()
    manager = _build_manager(tmp_path, plugin)
    sent_messages: list[pb.RuntimeMessage] = []

    async def _raise_probe(self, *, context):
        del self, context
        raise RuntimeError("probe runtime failed")

    monkeypatch.setattr(_InProcessProxy, "probe_runtime_capability", _raise_probe)

    async def fake_send(message: pb.RuntimeMessage) -> None:
        sent_messages.append(message)

    async def fake_request(message: pb.RuntimeMessage) -> pb.RuntimeMessage:
        request = message.data_request
        return build_data_response_message(
            request_id=f"resp-{request.request_id}",
            reply_to=request.request_id,
            task_id=request.task_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)
    accepted = await manager.assign_task(
        "assign-probe-failed-1",
        {
            "task_id": "task-probe-failed-1",
            "round_id": "job-probe-failed-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "task_type": "train",
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
        message.task_event.status_event.status
        for message in sent_messages
        if message.WhichOneof("payload") == "task_event"
        and message.task_event.WhichOneof("event_payload") == "status_event"
    ]
    assert status_codes[:3] == [pb.DISPATCHING, pb.SYNCING_ENV, pb.PROBING_RUNTIME]
    assert pb.BINDING_DEVICE not in status_codes
    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "task_result"]
    assert len(result_messages) == 1
    assert result_messages[0].task_result.status == pb.FAILED


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
            task_id=request.task_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_task(
        "assign-score-1",
        {
            "task_id": "task-score-1",
            "round_id": "job-score-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "task_type": "score",
            "dispatch_kind": "dispatchable",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {"topk": 10},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "task_result"]
    assert len(result_messages) == 1
    result = result_messages[0].task_result
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
    manager = TaskManager(
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
            task_id=request.task_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_task(
        "assign-score-strict-1",
        {
            "task_id": "task-score-strict-1",
            "round_id": "job-score-strict-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "task_type": "score",
            "dispatch_kind": "dispatchable",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {"topk": 10},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "task_result"]
    assert len(result_messages) == 1
    result = result_messages[0].task_result
    assert result.status == pb.FAILED
    assert "trained model is required" in str(result.error_message or "")


@pytest.mark.anyio
async def test_score_step_shared_model_sets_local_model_ref(tmp_path: Path):
    plugin = _CaptureModelParamsPlugin()
    manager = _build_manager(tmp_path, plugin)
    sent_messages: list[pb.RuntimeMessage] = []

    task_id = "task-score-shared-model-1"
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
            task_id=request.task_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_task(
        "assign-score-shared-model-1",
        {
            "task_id": task_id,
            "round_id": round_id,
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "task_type": "score",
            "dispatch_kind": "dispatchable",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {"topk": 10},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "task_result"]
    assert len(result_messages) == 1
    result = result_messages[0].task_result
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
            task_id=request.task_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_task(
        "assign-eval-1",
        {
            "task_id": "task-eval-1",
            "round_id": "job-eval-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "task_type": "eval",
            "dispatch_kind": "dispatchable",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {"topk": 10},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "task_result"]
    assert len(result_messages) == 1
    result = result_messages[0].task_result
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
                    task_id=request.task_id,
                    query_type=request.query_type,
                    items=items,
                    next_cursor=next_cursor,
                ).data_response
            )

        return build_data_response_message(
            request_id=f"resp-{request.request_id}",
            reply_to=request.request_id,
            task_id=request.task_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_task(
        "assign-al-stream-1",
        {
            "task_id": "task-al-stream-1",
            "round_id": "job-al-stream-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "task_type": "train",
            "dispatch_kind": "dispatchable",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {"topk": 2, "unlabeled_page_size": 3},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "task_result"]
    assert len(result_messages) == 1
    result = result_messages[0].task_result
    assert result.status == pb.SUCCEEDED
    assert len(result.candidates) == 0
    assert plugin.batch_calls == 0


@pytest.mark.anyio
async def test_predict_step_uses_samples_query_and_keeps_all_candidates(tmp_path: Path):
    plugin = _BatchScoringPlugin()
    manager = _build_manager(tmp_path, plugin)
    sent_messages: list[pb.RuntimeMessage] = []
    query_types: list[int] = []

    async def fake_send(message: pb.RuntimeMessage) -> None:
        sent_messages.append(message)

    async def fake_request(message: pb.RuntimeMessage) -> pb.RuntimeMessage:
        payload_type = message.WhichOneof("payload")
        assert payload_type == "data_request"
        request = message.data_request
        query_types.append(int(request.query_type))
        return build_data_response_message(
            request_id=f"resp-{request.request_id}",
            reply_to=request.request_id,
            task_id=request.task_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_task(
        "assign-predict-1",
        {
            "task_id": "task-predict-1",
            "round_id": "job-predict-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "task_type": "predict",
            "dispatch_kind": "dispatchable",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "task_result"]
    assert len(result_messages) == 1
    result = result_messages[0].task_result
    assert result.status == pb.SUCCEEDED
    assert len(result.candidates) == 4
    assert pb.SAMPLES in query_types
    assert pb.UNLABELED_SAMPLES not in query_types
    assert plugin.batch_calls >= 1


@pytest.mark.anyio
async def test_predict_step_rejects_invalid_prediction_snapshot_format(tmp_path: Path):
    plugin = _InvalidPredictionSnapshotPlugin()
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
            task_id=request.task_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_task(
        "assign-predict-invalid-snapshot-1",
        {
            "task_id": "task-predict-invalid-snapshot-1",
            "round_id": "job-predict-invalid-snapshot-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "task_type": "predict",
            "dispatch_kind": "dispatchable",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "task_result"]
    assert len(result_messages) == 1
    result = result_messages[0].task_result
    assert result.status == pb.FAILED
    assert "prediction_snapshot" in str(result.error_message or "")


@pytest.mark.anyio
async def test_predict_step_keep_all_overrides_topk_for_strict_plugins(tmp_path: Path):
    plugin = _BatchTopKStrictPlugin()
    manager = _build_manager(tmp_path, plugin)
    sent_messages: list[pb.RuntimeMessage] = []
    query_types: list[int] = []
    sample_items = _mock_data_items(pb.SAMPLES)

    async def fake_send(message: pb.RuntimeMessage) -> None:
        sent_messages.append(message)

    async def fake_request(message: pb.RuntimeMessage) -> pb.RuntimeMessage:
        payload_type = message.WhichOneof("payload")
        assert payload_type == "data_request"
        request = message.data_request
        query_types.append(int(request.query_type))
        if request.query_type == pb.SAMPLES:
            try:
                offset = int(str(request.cursor or "0") or "0")
            except Exception:
                offset = 0
            limit = int(request.limit or 0) or len(sample_items)
            limit = max(1, limit)
            page = sample_items[offset: offset + limit]
            next_cursor = str(offset + limit) if offset + limit < len(sample_items) else ""
            return build_data_response_message(
                request_id=f"resp-{request.request_id}",
                reply_to=request.request_id,
                task_id=request.task_id,
                query_type=request.query_type,
                items=page,
                next_cursor=next_cursor,
            )
        return build_data_response_message(
            request_id=f"resp-{request.request_id}",
            reply_to=request.request_id,
            task_id=request.task_id,
            query_type=request.query_type,
            items=[],
        )

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_task(
        "assign-predict-topk-strict-1",
        {
            "task_id": "task-predict-topk-strict-1",
            "round_id": "job-predict-topk-strict-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "task_type": "predict",
            "dispatch_kind": "dispatchable",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {
                "unlabeled_page_size": 2,
            },
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "task_result"]
    assert len(result_messages) == 1
    result = result_messages[0].task_result
    assert result.status == pb.SUCCEEDED
    assert len(result.candidates) == len(sample_items)
    assert pb.SAMPLES in query_types
    assert pb.UNLABELED_SAMPLES not in query_types
    assert plugin.batch_calls >= 2
    assert plugin.seen_topk and all(v > 0 for v in plugin.seen_topk)


@pytest.mark.anyio
async def test_predict_step_in_manual_mode_is_not_short_circuited(tmp_path: Path):
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
            task_id=request.task_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_task(
        "assign-manual-predict-1",
        {
            "task_id": "task-manual-predict-1",
            "round_id": "job-manual-predict-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "manual",
            "task_type": "predict",
            "dispatch_kind": "dispatchable",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {
                "sampling": {
                    "strategy": "uncertainty_1_minus_max_conf",
                },
            },
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "task_result"]
    assert len(result_messages) == 1
    result = result_messages[0].task_result
    assert result.status == pb.SUCCEEDED
    assert len(result.candidates) > 0
    assert plugin.predict_calls > 0


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

    accepted = await manager.assign_task(
        "assign-orchestrator-1",
        {
            "task_id": "task-orchestrator-1",
            "round_id": "job-orchestrator-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "task_type": "train",
            "dispatch_kind": "orchestrator",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "task_result"]
    assert len(result_messages) == 1
    result = result_messages[0].task_result
    assert result.status == pb.FAILED
    assert "orchestrator task should not be dispatched" in result.error_message
    assert request_calls == 0


@pytest.mark.anyio
async def test_legacy_task_type_is_rejected_on_executor(tmp_path: Path):
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

    accepted = await manager.assign_task(
        "assign-legacy-step-1",
        {
            "task_id": "task-legacy-step-1",
            "round_id": "job-legacy-step-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "manual",
            "task_type": "legacy_review_step",
            "dispatch_kind": "dispatchable",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "task_result"]
    assert len(result_messages) == 1
    result = result_messages[0].task_result
    assert result.status == pb.FAILED
    assert "unsupported task_type for executor pipeline" in result.error_message
    assert request_calls == 0


@pytest.mark.anyio
async def test_custom_task_type_uses_train_and_sampling_pipeline(tmp_path: Path):
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
            task_id=request.task_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_task(
        "assign-custom-1",
        {
            "task_id": "task-custom-1",
            "round_id": "job-custom-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "task_type": "custom",
            "dispatch_kind": "dispatchable",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {"topk": 10},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "task_result"]
    assert len(result_messages) == 1
    result = result_messages[0].task_result
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
            task_id=request.task_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_task(
        "assign-minimal-plugin-1",
        {
            "task_id": "task-minimal-plugin-1",
            "round_id": "job-minimal-plugin-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "active_learning",
            "task_type": "train",
            "dispatch_kind": "dispatchable",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {"topk": 2},
        },
    )
    assert accepted is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "task_result"]
    assert len(result_messages) == 1
    result = result_messages[0].task_result
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
            task_id=request.task_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)

    with pytest.raises(ValueError, match="unsupported mode"):
        await manager.assign_task(
            "assign-unknown-mode-1",
            {
                "task_id": "task-unknown-mode-1",
                "round_id": "job-unknown-mode-1",
                "project_id": "project-1",
                "input_commit_id": "commit-1",
                "plugin_id": plugin.plugin_id,
                "mode": "unexpected_mode",
                "task_type": "train",
                "dispatch_kind": "dispatchable",
                "round_index": 1,
                "query_strategy": "uncertainty_1_minus_max_conf",
                "resolved_params": {},
            },
        )

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "task_result"]
    assert len(result_messages) == 0
    assert request_calls == 0
    assert plugin.prepare_samples_count == 0
    assert plugin.predict_calls == 0


@pytest.mark.anyio
async def test_stop_task_forces_cancelled_result(tmp_path: Path):
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
            task_id=request.task_id,
            query_type=request.query_type,
            items=_mock_data_items(request.query_type),
        )

    manager.set_transport(fake_send, fake_request)

    accepted = await manager.assign_task(
        "assign-stop-1",
        {
            "task_id": "task-stop-1",
            "round_id": "job-stop-1",
            "project_id": "project-1",
            "input_commit_id": "commit-1",
            "plugin_id": plugin.plugin_id,
            "mode": "simulation",
            "task_type": "eval",
            "dispatch_kind": "dispatchable",
            "round_index": 1,
            "query_strategy": "uncertainty_1_minus_max_conf",
            "resolved_params": {},
        },
    )
    assert accepted is True
    await asyncio.sleep(0.1)
    stopped = await manager.stop_task("task-stop-1")
    assert stopped is True
    assert manager._task is not None  # noqa: SLF001
    await asyncio.wait_for(manager._task, timeout=2.0)  # noqa: SLF001

    result_messages = [m for m in sent_messages if m.WhichOneof("payload") == "task_result"]
    assert len(result_messages) == 1
    assert result_messages[0].task_result.status == pb.CANCELLED
