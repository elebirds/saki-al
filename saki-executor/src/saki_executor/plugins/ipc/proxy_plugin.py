from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any
import uuid

from saki_executor.core.config import settings
from saki_executor.plugins.ipc.client import PluginWorkerClient
from saki_plugin_sdk import (
    ExecutionBindingContext,
    EventCallback,
    ExecutorPlugin,
    RuntimeCapabilitySnapshot,
    StepRuntimeContext,
    StepRuntimeRequirements,
    TrainOutput,
    WorkspaceProtocol,
)
from saki_plugin_sdk.ipc import protocol


class SubprocessPluginProxy(ExecutorPlugin):
    def __init__(
        self,
        *,
        metadata_plugin: Any,
        step_id: str,
        emit: EventCallback,
        python_executable: str | Path | None = None,
        entrypoint_module: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> None:
        self._metadata = metadata_plugin
        self._step_id = step_id
        self._emit = emit
        self._worker = PluginWorkerClient(
            plugin_id=self._metadata.plugin_id,
            step_id=self._step_id,
            event_handler=self._on_worker_event,
            python_executable=python_executable,
            entrypoint_module=entrypoint_module,
            extra_env=extra_env,
        )
        self._binding_context: ExecutionBindingContext | None = None

    @property
    def plugin_id(self) -> str:
        return self._metadata.plugin_id

    @property
    def version(self) -> str:
        return self._metadata.version

    @property
    def display_name(self) -> str:
        return self._metadata.display_name

    @property
    def supported_step_types(self) -> list[str]:
        return list(self._metadata.supported_step_types)

    @property
    def supported_strategies(self) -> list[str]:
        return list(self._metadata.supported_strategies)

    @property
    def request_config_schema(self) -> dict[str, Any]:
        return dict(self._metadata.request_config_schema)

    @property
    def default_request_config(self) -> dict[str, Any]:
        return dict(self._metadata.default_request_config)

    @property
    def supported_accelerators(self) -> list[str]:
        return list(self._metadata.supported_accelerators)

    @property
    def supports_auto_fallback(self) -> bool:
        return bool(self._metadata.supports_auto_fallback)

    def validate_params(
        self,
        params: dict[str, Any],
        *,
        context: StepRuntimeContext | ExecutionBindingContext | None = None,
    ) -> None:
        self._metadata.validate_params(params, context=context)

    def get_step_runtime_requirements(self, step_type: str) -> StepRuntimeRequirements:
        return self._metadata.get_step_runtime_requirements(step_type)

    async def probe_runtime_capability(
        self,
        *,
        context: StepRuntimeContext,
    ) -> RuntimeCapabilitySnapshot:
        await self._worker.start()
        payload_dir = self._payload_dir_for_step_cache()
        result_path = payload_dir / f"runtime_capability_{uuid.uuid4().hex}.json"
        reply = await self._worker.request(
            action="probe_runtime_capability",
            payload={
                "result_path": str(result_path),
            },
            runtime_context=context,
        )
        output_path = Path(reply.result_path or str(result_path))
        payload = protocol.read_json(output_path)
        return protocol.parse_runtime_capability(payload)

    async def bind_execution_context(self, context: ExecutionBindingContext) -> None:
        await self._worker.start()
        await self._worker.request(
            action="bind_execution_context",
            payload={},
            execution_binding_context=context,
        )
        self._binding_context = context

    async def prepare_data(
        self,
        workspace: WorkspaceProtocol,
        labels: list[dict[str, Any]],
        samples: list[dict[str, Any]],
        annotations: list[dict[str, Any]],
        dataset_ir: Any,
        splits: dict[str, list[dict[str, Any]]] | None = None,
        *,
        context: ExecutionBindingContext,
    ) -> None:
        await self._worker.start()
        payload_dir = self._payload_dir(workspace)
        labels_path = payload_dir / "prepare_labels.json"
        samples_path = payload_dir / "prepare_samples.json"
        annotations_path = payload_dir / "prepare_annotations.json"
        splits_path = payload_dir / "prepare_splits.json"
        dataset_ir_path = payload_dir / "prepare_dataset_ir.pb"
        protocol.write_json(labels_path, labels)
        protocol.write_json(samples_path, samples)
        protocol.write_json(annotations_path, annotations)
        protocol.write_json(splits_path, splits or {})
        if not hasattr(dataset_ir, "SerializeToString"):
            raise RuntimeError("dataset_ir does not support SerializeToString")
        dataset_ir_path.write_bytes(dataset_ir.SerializeToString())

        await self._worker.request(
            action="prepare_data",
            payload={
                "workspace_root": str(workspace.root),
                "labels_path": str(labels_path),
                "samples_path": str(samples_path),
                "annotations_path": str(annotations_path),
                "splits_path": str(splits_path),
                "dataset_ir_path": str(dataset_ir_path),
            },
            execution_binding_context=context,
        )

    async def train(
        self,
        workspace: WorkspaceProtocol,
        params: dict[str, Any],
        emit: EventCallback,
        *,
        context: ExecutionBindingContext,
    ) -> TrainOutput:
        return await self._run_train_output_action(
            action="train",
            workspace=workspace,
            params=params,
            emit=emit,
            context=context,
        )

    async def eval(
        self,
        workspace: WorkspaceProtocol,
        params: dict[str, Any],
        emit: EventCallback,
        *,
        context: ExecutionBindingContext,
    ) -> TrainOutput:
        return await self._run_train_output_action(
            action="eval",
            workspace=workspace,
            params=params,
            emit=emit,
            context=context,
        )

    async def predict(
        self,
        workspace: WorkspaceProtocol,
        params: dict[str, Any],
        emit: EventCallback,
        *,
        context: ExecutionBindingContext,
    ) -> TrainOutput:
        return await self._run_train_output_action(
            action="predict",
            workspace=workspace,
            params=params,
            emit=emit,
            context=context,
        )

    async def _run_train_output_action(
        self,
        *,
        action: str,
        workspace: WorkspaceProtocol,
        params: dict[str, Any],
        emit: EventCallback,
        context: ExecutionBindingContext,
    ) -> TrainOutput:
        self._emit = emit
        await self._worker.start()
        payload_dir = self._payload_dir(workspace)
        params_path = payload_dir / f"{action}_params.json"
        result_path = payload_dir / f"{action}_result_{uuid.uuid4().hex}.json"
        protocol.write_json(params_path, params)
        reply = await self._worker.request(
            action=action,
            payload={
                "workspace_root": str(workspace.root),
                "params_path": str(params_path),
                "result_path": str(result_path),
            },
            execution_binding_context=context,
        )
        output_path = Path(reply.result_path or str(result_path))
        if not output_path.exists():
            raise RuntimeError(f"worker train result file not found: {output_path}")
        output_payload = protocol.read_json(output_path)
        if not isinstance(output_payload, dict):
            raise RuntimeError("invalid worker train result payload")
        return protocol.train_output_from_dict(output_payload)

    async def predict_unlabeled(
        self,
        workspace: WorkspaceProtocol,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
        *,
        context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        return await self.predict_unlabeled_batch(
            workspace=workspace,
            unlabeled_samples=unlabeled_samples,
            strategy=strategy,
            params=params,
            context=context,
        )

    async def predict_unlabeled_batch(
        self,
        workspace: WorkspaceProtocol,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
        *,
        context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        await self._worker.start()
        payload_dir = self._payload_dir(workspace)
        samples_path = payload_dir / "predict_samples.json"
        params_path = payload_dir / "predict_params.json"
        result_path = payload_dir / f"predict_result_{uuid.uuid4().hex}.json"
        protocol.write_json(samples_path, unlabeled_samples)
        protocol.write_json(params_path, params)

        reply = await self._worker.request(
            action="predict_unlabeled_batch",
            payload={
                "workspace_root": str(workspace.root),
                "samples_path": str(samples_path),
                "strategy": strategy,
                "params_path": str(params_path),
                "result_path": str(result_path),
            },
            execution_binding_context=context,
        )
        output_path = Path(reply.result_path or str(result_path))
        if not output_path.exists():
            raise RuntimeError(f"worker predict result file not found: {output_path}")
        output_payload = protocol.read_json(output_path)
        if not isinstance(output_payload, dict):
            raise RuntimeError("invalid worker predict result payload")
        rows = output_payload.get("candidates")
        if not isinstance(rows, list):
            return []
        return [item for item in rows if isinstance(item, dict)]

    async def stop(self, step_id: str) -> None:
        del step_id
        await self._worker.terminate()
        self._cleanup_step_payload_dir()

    async def shutdown(self) -> None:
        await self._worker.close()
        self._cleanup_step_payload_dir()

    async def _on_worker_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if event_type == "worker":
            level = str(payload.get("level") or "INFO")
            message = str(payload.get("message") or "")
            await self._emit(
                "log",
                {
                    "level": level,
                    "message": message,
                    "raw_message": str(payload.get("raw_message") or message),
                    "meta": {
                        "source": "worker_lifecycle",
                        "plugin_id": self.plugin_id,
                    },
                },
            )
            return
        await self._emit(event_type, payload)

    @staticmethod
    def _payload_dir(workspace: WorkspaceProtocol) -> Path:
        path = workspace.cache_dir / "plugin_worker_payloads"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _payload_dir_for_step_cache(self) -> Path:
        path = Path(settings.PLUGIN_WORKER_IPC_DIR) / "payloads" / self._step_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _cleanup_step_payload_dir(self) -> None:
        path = Path(settings.PLUGIN_WORKER_IPC_DIR) / "payloads" / self._step_id
        shutil.rmtree(path, ignore_errors=True)
