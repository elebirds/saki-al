from __future__ import annotations

from typing import Any

import pytest

from saki_plugin_sdk import (
    DeviceBinding,
    ExecutionBindingContext,
    EventCallback,
    ExecutorPlugin,
    HostCapabilitySnapshot,
    PluginManifest,
    PluginValidationError,
    RuntimeCapabilitySnapshot,
    TaskRuntimeContext,
    TrainOutput,
    WorkspaceProtocol,
)


class _DummyPlugin(ExecutorPlugin):
    def __init__(self) -> None:
        super().__init__()
        self._manifest = PluginManifest.model_validate(
            {
                "plugin_id": "dummy_v2",
                "version": "3.0.0",
                "display_name": "Dummy V3",
                "supported_task_types": ["train", "score"],
                "supported_strategies": ["random_baseline"],
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
                    "title": "Dummy Config",
                    "fields": [
                        {"key": "epochs", "label": "Epochs", "type": "integer", "required": True, "min": 1, "default": 5},
                        {"key": "batch", "label": "Batch", "type": "integer", "required": True, "min": 1, "default": 8},
                    ],
                },
                "default_config": {
                    "epochs": 5,
                    "batch": 8,
                },
                "task_runtime_requirements": {
                    "score": {
                        "requires_prepare_data": True,
                        "requires_trained_model": True,
                        "primary_model_artifact_name": "score.pt",
                    }
                },
            }
        )

    async def train(
        self,
        workspace: WorkspaceProtocol,
        params: dict[str, Any],
        emit: EventCallback,
        *,
        context: ExecutionBindingContext,
    ) -> TrainOutput:
        del workspace, params, emit, context
        return TrainOutput(metrics={}, artifacts=[])

    async def predict_unlabeled(
        self,
        workspace: WorkspaceProtocol,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
        *,
        context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        del workspace, unlabeled_samples, strategy, params, context
        return []


def _context() -> TaskRuntimeContext:
    return TaskRuntimeContext(
        task_id="step-1",
        round_id="round-1",
        round_index=1,
        attempt=1,
        task_type="train",
        mode="active_learning",
        split_seed=11,
        train_seed=22,
        sampling_seed=33,
        resolved_device_backend="cpu",
    )


def _execution_context() -> ExecutionBindingContext:
    return ExecutionBindingContext(
        task_context=_context(),
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


def test_executor_plugin_resolve_config_applies_default_and_coercion():
    plugin = _DummyPlugin()
    config = plugin.resolve_config(
        "active_learning",
        {"epochs": "12"},
        context=_context().to_dict(),
    )
    assert config.epochs == 12
    assert config.batch == 8


def test_executor_plugin_validate_params_uses_schema():
    plugin = _DummyPlugin()
    plugin.validate_params({"epochs": 3, "batch": 4}, context=_context())
    plugin.validate_params({"epochs": 3, "batch": 4}, context=_execution_context())
    with pytest.raises(PluginValidationError):
        plugin.validate_params({"epochs": 0, "batch": 4}, context=_context())


def test_executor_plugin_runtime_requirements_use_manifest_overrides():
    plugin = _DummyPlugin()
    score = plugin.get_task_runtime_requirements("score")
    train = plugin.get_task_runtime_requirements("train")
    assert score.requires_prepare_data is True
    assert score.requires_trained_model is True
    assert score.primary_model_artifact_name == "score.pt"
    assert train.primary_model_artifact_name == "best.pt"
