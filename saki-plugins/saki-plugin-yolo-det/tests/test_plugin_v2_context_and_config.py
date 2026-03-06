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
    TaskRuntimeContext,
    TrainOutput,
    Workspace,
    WorkspaceProtocol,
)
from saki_plugin_yolo_det.config_service import YoloConfigService
from saki_plugin_yolo_det.predict_service import YoloPredictService
from saki_plugin_yolo_det.prepare_pipeline import _build_label_index
from saki_plugin_yolo_det.runtime_service import YoloRuntimeService
from saki_plugin_yolo_det.plugin import YoloDetectionPlugin
from saki_plugin_yolo_det.types import TrainConfig
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as irpb


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

    async def stop(self, task_id: str) -> None:
        del task_id


@pytest.mark.anyio
async def test_plugin_facade_forwards_context_to_runtime(tmp_path):
    plugin = YoloDetectionPlugin()
    runtime_stub = _RuntimeStub()
    plugin._runtime = runtime_stub  # type: ignore[assignment]

    workspace = Workspace(str(tmp_path / "runs"), "step-ctx-1")
    workspace.ensure()
    task_context = TaskRuntimeContext(
        task_id="step-ctx-1",
        round_id="round-ctx-1",
        round_index=4,
        attempt=2,
        task_type="train",
        mode="simulation",
        split_seed=11,
        train_seed=22,
        sampling_seed=33,
        resolved_device_backend="cpu",
    )
    context = ExecutionBindingContext(
        task_context=task_context,
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
    forwarded_task_context = runtime_stub.last_train_context.task_context
    assert forwarded_task_context.task_type == "train"
    assert forwarded_task_context.mode == "simulation"
    assert forwarded_task_context.split_seed == 11
    assert forwarded_task_context.train_seed == 22
    assert forwarded_task_context.sampling_seed == 33


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


@pytest.mark.anyio
async def test_runtime_prepare_data_ignores_yolo_task_split_hint(tmp_path: Path, monkeypatch):
    runtime = YoloRuntimeService()
    workspace = Workspace(str(tmp_path / "runs"), "step-prepare-1")
    workspace.ensure()
    dataset_ir = irpb.DataBatchIR()
    captured: dict[str, Any] = {}

    def _fake_prepare_yolo_dataset(**kwargs):
        captured["yolo_task"] = kwargs.get("yolo_task")

    monkeypatch.setattr(
        "saki_plugin_yolo_det.runtime_service.prepare_yolo_dataset",
        _fake_prepare_yolo_dataset,
    )

    task_context = TaskRuntimeContext(
        task_id="step-prepare-1",
        round_id="round-prepare-1",
        round_index=0,
        attempt=1,
        task_type="train",
        mode="manual",
        split_seed=1,
        train_seed=2,
        sampling_seed=3,
        resolved_device_backend="cpu",
    )
    context = ExecutionBindingContext(
        task_context=task_context,
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

    await runtime.prepare_data(
        workspace=workspace,
        labels=[],
        samples=[],
        annotations=[],
        dataset_ir=dataset_ir,
        splits={"yolo_task": "obb"},
        context=context,
    )
    assert captured["yolo_task"] == "detect"


@pytest.mark.anyio
async def test_runtime_train_reads_split_seed_from_plugin_config_attrs(tmp_path: Path, monkeypatch):
    runtime = YoloRuntimeService()
    workspace = Workspace(str(tmp_path / "runs"), "step-train-1")
    workspace.ensure()
    (workspace.artifacts_dir / "best.pt").write_bytes(b"")
    emitted_logs: list[str] = []

    async def _fake_resolve_train_config(**kwargs) -> TrainConfig:
        plugin_config = kwargs["plugin_config"]
        assert int(getattr(plugin_config, "split_seed", -1)) == 11
        return TrainConfig(
            epochs=1,
            batch=1,
            imgsz=640,
            patience=1,
            device="cpu",
            requested_device="auto",
            resolved_backend="cpu",
            resolved_base_model="yolov8n.pt",
            train_seed=22,
            deterministic=False,
            strong_deterministic=False,
            yolo_task="detect",
        )

    async def _fake_run_train_with_epoch_stream(**kwargs) -> dict[str, Any]:
        return {
            "metrics": {"loss": 1.0},
            "history": [],
            "save_dir": str(workspace.artifacts_dir),
            "best_path": str(workspace.artifacts_dir / "best.pt"),
            "extra_artifacts": [],
        }

    monkeypatch.setattr("saki_plugin_yolo_det.runtime_service.resolve_train_config", _fake_resolve_train_config)
    monkeypatch.setattr("saki_plugin_yolo_det.runtime_service.run_train_with_epoch_stream", _fake_run_train_with_epoch_stream)
    monkeypatch.setattr("saki_plugin_yolo_det.runtime_service.load_prepare_stats", lambda _workspace: {})
    monkeypatch.setattr(
        "saki_plugin_yolo_det.runtime_service.normalize_training_metrics",
        lambda *, metrics, prepare_stats, to_int, to_bool: dict(metrics),
    )

    task_context = TaskRuntimeContext(
        task_id="step-train-1",
        round_id="round-train-1",
        round_index=1,
        attempt=1,
        task_type="train",
        mode="active_learning",
        split_seed=11,
        train_seed=22,
        sampling_seed=33,
        resolved_device_backend="cpu",
    )
    context = ExecutionBindingContext(
        task_context=task_context,
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
        if event_type == "log":
            emitted_logs.append(str(payload.get("message") or ""))

    output = await runtime.train(
        workspace=workspace,
        params={"yolo_task": "detect", "model_source": "preset"},
        emit=_emit,
        context=context,
    )
    assert output.metrics.get("loss") == 1.0
    assert any("split_seed=11" in msg for msg in emitted_logs)


def test_prepare_pipeline_build_label_index_outputs_class_schema_rows():
    rows, label_id_to_idx, names = _build_label_index(
        [
            {"id": "label-b", "name": "bus"},
            {"id": "label-a", "name": "car"},
        ]
    )
    assert label_id_to_idx == {"label-b": 0, "label-a": 1}
    assert names == {0: "bus", 1: "car"}
    assert rows == [
        {"class_index": 0, "label_id": "label-b", "class_name": "bus", "class_name_norm": "bus"},
        {"class_index": 1, "label_id": "label-a", "class_name": "car", "class_name_norm": "car"},
    ]


def test_predict_service_extract_predictions_contains_class_index_and_name():
    service = YoloPredictService(
        stop_flag=__import__("threading").Event(),
        config_service=YoloConfigService(),
        load_yolo=lambda: None,
    )

    class _Array:
        def __init__(self, values):
            self._values = values

        def cpu(self):
            return self

        def tolist(self):
            return list(self._values)

    class _Boxes:
        def __init__(self):
            self.cls = _Array([1])
            self.conf = _Array([0.88])
            self.xyxy = _Array([[10.0, 20.0, 30.0, 40.0]])

        def __len__(self):
            return 1

    class _Result:
        def __init__(self):
            self.boxes = _Boxes()
            self.names = {1: "car"}

    rows = service._extract_predictions(_Result())
    assert len(rows) == 1
    row = rows[0]
    assert row["class_index"] == 1
    assert row["class_name"] == "car"
    assert row["confidence"] == pytest.approx(0.88)
    rect = (row.get("geometry") or {}).get("rect") or {}
    assert rect.get("x") == pytest.approx(10.0)
    assert rect.get("y") == pytest.approx(20.0)
    assert rect.get("width") == pytest.approx(20.0)
    assert rect.get("height") == pytest.approx(20.0)
