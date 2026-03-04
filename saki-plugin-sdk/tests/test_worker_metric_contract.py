from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from saki_plugin_sdk import (
    DeviceBinding,
    ExecutionBindingContext,
    ExecutorPlugin,
    HostCapabilitySnapshot,
    RuntimeCapabilitySnapshot,
    StepRuntimeContext,
    TrainOutput,
)
from saki_plugin_sdk.exceptions import PluginMetricContractError
from saki_plugin_sdk.ipc import protocol
from saki_plugin_sdk.ipc.worker import _run_train_like


class _FakePubSocket:
    def __init__(self) -> None:
        self.frames: list[list[bytes]] = []

    def send_multipart(self, frames: list[bytes]) -> None:
        self.frames.append(list(frames))


def _execution_context(step_type: str) -> ExecutionBindingContext:
    return ExecutionBindingContext(
        step_context=StepRuntimeContext(
            step_id="step-contract",
            round_id="round-contract",
            round_index=1,
            attempt=1,
            step_type=step_type,
            mode="active_learning",
            split_seed=1,
            train_seed=2,
            sampling_seed=3,
            resolved_device_backend="cpu",
        ),
        host_capability=HostCapabilitySnapshot.from_dict(
            {
                "cpu_workers": 8,
                "memory_mb": 8192,
                "gpus": [],
                "metal_available": False,
                "platform": "darwin",
                "arch": "arm64",
                "driver_info": {},
            }
        ),
        runtime_capability=RuntimeCapabilitySnapshot(
            framework="torch",
            framework_version="2.2.0",
            backends=["cpu"],
            backend_details={},
            errors=[],
        ),
        device_binding=DeviceBinding(
            backend="cpu",
            device_spec="cpu",
            precision="fp32",
            profile_id="cpu",
            reason="test",
            fallback_applied=False,
        ),
        profile_id="cpu",
    )


def test_run_train_like_fails_when_final_metrics_have_non_canonical_key(tmp_path: Path):
    class _Plugin(ExecutorPlugin):
        async def train(self, workspace, params, emit, *, context):  # type: ignore[override]
            del workspace, params, emit, context
            return TrainOutput(metrics={"map50": 0.5, "metrics/mAP50(B)": 0.6}, artifacts=[])

        async def predict_unlabeled(
            self,
            workspace,
            unlabeled_samples,
            strategy,
            params,
            *,
            context,
        ):  # type: ignore[override]
            del workspace, unlabeled_samples, strategy, params, context
            return []

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    params_path = tmp_path / "params.json"
    result_path = tmp_path / "result.json"
    protocol.write_json(params_path, {})

    with pytest.raises(PluginMetricContractError, match="METRIC_CONTRACT_VIOLATION"):
        asyncio.run(
            _run_train_like(
                plugin=_Plugin(),
                payload={
                    "workspace_root": str(workspace_root),
                    "params_path": str(params_path),
                    "result_path": str(result_path),
                },
                step_id="step-contract",
                request_id="req-contract",
                pub_socket=_FakePubSocket(),
                method_name="train",
                execution_context=_execution_context("train"),
            )
        )


def test_run_train_like_fails_when_metric_event_violate_contract(tmp_path: Path):
    class _Plugin(ExecutorPlugin):
        async def eval(self, workspace, params, emit, *, context):  # type: ignore[override]
            del workspace, params, context
            await emit(
                "metric",
                {"step": 1, "epoch": 0, "metrics": {"map50": 0.7, "metrics/mAP50(B)": 0.71}},
            )
            return TrainOutput(
                metrics={"map50": 0.7, "map50_95": 0.5, "precision": 0.8, "recall": 0.6},
                artifacts=[],
            )

        async def train(self, workspace, params, emit, *, context):  # type: ignore[override]
            del workspace, params, emit, context
            raise RuntimeError("not used")

        async def predict_unlabeled(
            self,
            workspace,
            unlabeled_samples,
            strategy,
            params,
            *,
            context,
        ):  # type: ignore[override]
            del workspace, unlabeled_samples, strategy, params, context
            return []

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    params_path = tmp_path / "params.json"
    result_path = tmp_path / "result.json"
    protocol.write_json(params_path, {})

    with pytest.raises(PluginMetricContractError, match="METRIC_CONTRACT_VIOLATION"):
        asyncio.run(
            _run_train_like(
                plugin=_Plugin(),
                payload={
                    "workspace_root": str(workspace_root),
                    "params_path": str(params_path),
                    "result_path": str(result_path),
                },
                step_id="step-contract",
                request_id="req-contract",
                pub_socket=_FakePubSocket(),
                method_name="eval",
                execution_context=_execution_context("eval"),
            )
        )


def test_run_train_like_allows_empty_final_metrics(tmp_path: Path):
    class _Plugin(ExecutorPlugin):
        async def train(self, workspace, params, emit, *, context):  # type: ignore[override]
            del workspace, params, emit, context
            return TrainOutput(metrics={}, artifacts=[])

        async def predict_unlabeled(
            self,
            workspace,
            unlabeled_samples,
            strategy,
            params,
            *,
            context,
        ):  # type: ignore[override]
            del workspace, unlabeled_samples, strategy, params, context
            return []

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    params_path = tmp_path / "params.json"
    result_path = tmp_path / "result.json"
    protocol.write_json(params_path, {})

    output_path = asyncio.run(
        _run_train_like(
            plugin=_Plugin(),
            payload={
                "workspace_root": str(workspace_root),
                "params_path": str(params_path),
                "result_path": str(result_path),
            },
            step_id="step-contract",
            request_id="req-contract",
            pub_socket=_FakePubSocket(),
            method_name="train",
            execution_context=_execution_context("train"),
        )
    )
    payload = protocol.read_json(Path(output_path))
    assert payload["metrics"] == {}
