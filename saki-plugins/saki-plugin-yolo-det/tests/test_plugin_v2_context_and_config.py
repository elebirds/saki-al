from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from saki_plugin_sdk import (
    DeviceBinding,
    ExecutionBindingContext,
    HostCapabilitySnapshot,
    PluginManifest,
    RuntimeCapabilitySnapshot,
    StepRuntimeContext,
    TrainOutput,
    Workspace,
    WorkspaceProtocol,
)
from saki_plugin_yolo_det.config_service import YoloConfigService
from saki_plugin_yolo_det.plugin import YoloDetectionPlugin


class _RuntimeStub:
    def __init__(self) -> None:
        self.last_train_context: ExecutionBindingContext | None = None

    def validate_params(self, params: dict[str, Any]) -> None:
        del params

    async def prepare_data(self, **kwargs) -> None:
        del kwargs

    async def train(
        self,
        *,
        workspace: WorkspaceProtocol,
        params: dict[str, Any],
        emit,
        context: ExecutionBindingContext,
    ) -> TrainOutput:
        del workspace, params, emit
        self.last_train_context = context
        return TrainOutput(metrics={"ok": 1.0}, artifacts=[])

    async def eval(
        self,
        *,
        workspace: WorkspaceProtocol,
        params: dict[str, Any],
        emit,
        context: ExecutionBindingContext,
    ) -> TrainOutput:
        del workspace, params, emit, context
        return TrainOutput(metrics={"ok": 1.0}, artifacts=[])

    async def predict_unlabeled(
        self,
        *,
        workspace: WorkspaceProtocol,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
        context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        del workspace, unlabeled_samples, strategy, params, context
        return []

    async def predict_unlabeled_batch(
        self,
        *,
        workspace: WorkspaceProtocol,
        unlabeled_samples: list[dict[str, Any]],
        strategy: str,
        params: dict[str, Any],
        context: ExecutionBindingContext,
    ) -> list[dict[str, Any]]:
        del workspace, unlabeled_samples, strategy, params, context
        return []

    def probe_runtime_capability(self) -> RuntimeCapabilitySnapshot:
        return RuntimeCapabilitySnapshot(
            framework="torch",
            framework_version="2.2.0",
            backends=["cpu"],
            backend_details={},
            errors=[],
        )

    async def stop(self, step_id: str) -> None:
        del step_id


@pytest.mark.anyio
async def test_plugin_facade_forwards_context_to_runtime(tmp_path):
    plugin = YoloDetectionPlugin()
    runtime_stub = _RuntimeStub()
    plugin._runtime = runtime_stub  # type: ignore[assignment]

    workspace = Workspace(str(tmp_path / "runs"), "step-ctx-1")
    workspace.ensure()
    step_context = StepRuntimeContext(
        step_id="step-ctx-1",
        round_id="round-ctx-1",
        round_index=4,
        attempt=2,
        step_type="train",
        mode="simulation",
        split_seed=11,
        train_seed=22,
        sampling_seed=33,
        resolved_device_backend="cpu",
    )
    context = ExecutionBindingContext(
        step_context=step_context,
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

    async def _emit(event_type: str, payload: dict[str, Any]) -> None:
        del event_type, payload

    await plugin.train(
        workspace=workspace,
        params={"epochs": 1},
        emit=_emit,
        context=context,
    )
    assert runtime_stub.last_train_context is not None
    forwarded_step_context = runtime_stub.last_train_context.step_context
    assert forwarded_step_context.step_type == "train"
    assert forwarded_step_context.mode == "simulation"
    assert forwarded_step_context.split_seed == 11
    assert forwarded_step_context.train_seed == 22
    assert forwarded_step_context.sampling_seed == 33


def test_config_service_uses_manifest_options_as_single_source():
    service = YoloConfigService()
    fields = service.manifest.config_schema.get("fields", [])
    preset_field = next(
        (item for item in fields if isinstance(item, dict) and item.get("key") == "model_preset"),
        None,
    )
    assert isinstance(preset_field, dict)
    options = preset_field.get("options") if isinstance(preset_field.get("options"), list) else []

    detect_allowed = [
        str(item.get("value") or "").strip()
        for item in options
        if isinstance(item, dict) and "detect" in str(item.get("visible") or "")
    ]
    obb_allowed = [
        str(item.get("value") or "").strip()
        for item in options
        if isinstance(item, dict) and "obb" in str(item.get("visible") or "")
    ]
    assert detect_allowed
    assert obb_allowed

    detect_default = service.resolve_config(
        {
            "yolo_task": "detect",
            "model_source": "preset",
        }
    )
    obb_default = service.resolve_config(
        {
            "yolo_task": "obb",
            "model_source": "preset",
        }
    )
    assert str(detect_default.model_preset) == detect_allowed[0]
    assert str(obb_default.model_preset) == obb_allowed[0]


def test_config_service_rejects_preset_task_mismatch():
    service = YoloConfigService()
    with pytest.raises(ValueError, match="not allowed"):
        service.resolve_config(
            {
                "yolo_task": "detect",
                "model_source": "preset",
                "model_preset": "yolov8n-obb.pt",
            }
        )
    with pytest.raises(ValueError, match="not allowed"):
        service.resolve_config(
            {
                "yolo_task": "obb",
                "model_source": "preset",
                "model_preset": "yolov8n.pt",
            }
        )


def test_config_service_init_fails_when_task_has_no_preset(monkeypatch):
    plugin_yml = Path(__file__).resolve().parents[1] / "plugin.yml"
    manifest = PluginManifest.from_yaml(plugin_yml)
    schema = dict(manifest.config_schema)
    fields = list(schema.get("fields") or [])
    for field in fields:
        if not isinstance(field, dict) or str(field.get("key") or "") != "model_preset":
            continue
        options = field.get("options")
        if not isinstance(options, list):
            continue
        field["options"] = [
            item
            for item in options
            if isinstance(item, dict) and "detect" in str(item.get("visible") or "")
        ]
    bad_manifest = manifest.model_copy(update={"config_schema": schema})

    monkeypatch.setattr(
        "saki_plugin_yolo_det.config_service.PluginManifest.from_yaml",
        lambda _path: bad_manifest,
    )
    with pytest.raises(ValueError, match="at least one preset"):
        YoloConfigService()
