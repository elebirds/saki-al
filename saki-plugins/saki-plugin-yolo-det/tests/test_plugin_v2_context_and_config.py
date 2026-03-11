from __future__ import annotations

import json
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


def test_plugin_init_config_log_uses_request_schema_property() -> None:
    plugin = YoloDetectionPlugin()
    text = plugin._build_init_config_log()
    assert "插件初始化配置摘要" in text


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


def test_config_service_aug_iou_requires_identity_when_strategy_is_aug_iou():
    service = YoloConfigService()
    cfg = service.resolve_config(
        {
            "yolo_task": "detect",
            "model_source": "preset",
        },
        strategy="aug_iou_disagreement",
    )
    augs = list(getattr(cfg, "aug_iou_enabled_augs", []))
    assert "identity" in augs
    assert str(getattr(cfg, "aug_iou_iou_mode", "")) == "obb"
    assert int(getattr(cfg, "aug_iou_boundary_d", 0)) == 3
    assert int(getattr(cfg, "workers", -1)) == 2

    with pytest.raises(ValueError, match="must include 'identity'"):
        service.resolve_config(
            {
                "yolo_task": "detect",
                "model_source": "preset",
                "aug_iou_enabled_augs": ["hflip", "rot90"],
            },
            strategy="aug_iou_disagreement",
        )


def test_config_service_aug_iou_mode_and_boundary_d_validation():
    service = YoloConfigService()
    with pytest.raises(Exception, match="aug_iou_iou_mode"):
        service.resolve_config(
            {
                "yolo_task": "detect",
                "model_source": "preset",
                "aug_iou_iou_mode": "bad_mode",
            },
            strategy="aug_iou_disagreement",
        )

    cfg = service.resolve_config(
        {
            "yolo_task": "detect",
            "model_source": "preset",
            "aug_iou_iou_mode": "boundary",
            "aug_iou_boundary_d": 999,
        },
        strategy="aug_iou_disagreement",
    )
    assert str(getattr(cfg, "aug_iou_iou_mode", "")) == "boundary"
    assert int(getattr(cfg, "aug_iou_boundary_d", 0)) == 128


def test_config_service_workers_default_and_clamp():
    service = YoloConfigService()
    default_cfg = service.resolve_config(
        {
            "yolo_task": "detect",
            "model_source": "preset",
        }
    )
    assert int(getattr(default_cfg, "workers", -1)) == 2

    low_cfg = service.resolve_config(
        {
            "yolo_task": "detect",
            "model_source": "preset",
            "workers": -9,
        }
    )
    assert int(getattr(low_cfg, "workers", -1)) == 0

    high_cfg = service.resolve_config(
        {
            "yolo_task": "detect",
            "model_source": "preset",
            "workers": 999,
        }
    )
    assert int(getattr(high_cfg, "workers", -1)) == 32


def test_config_service_train_budget_mode_defaults_to_fixed_epochs():
    service = YoloConfigService()
    cfg = service.resolve_config(
        {
            "yolo_task": "detect",
            "model_source": "preset",
        }
    )
    assert str(getattr(cfg, "train_budget_mode", "")) == "fixed_epochs"
    assert int(getattr(cfg, "target_updates", -1)) == 0
    assert int(getattr(cfg, "min_epochs", -1)) == 1
    assert int(getattr(cfg, "max_epochs", -1)) == 1000
    assert bool(getattr(cfg, "budget_disable_early_stop", False)) is True


def test_config_service_target_updates_validation():
    service = YoloConfigService()
    with pytest.raises(ValueError, match="target_updates must be > 0"):
        service.resolve_config(
            {
                "yolo_task": "detect",
                "model_source": "preset",
                "train_budget_mode": "target_updates",
            }
        )
    with pytest.raises(ValueError, match="target_updates must be > 0"):
        service.resolve_config(
            {
                "yolo_task": "detect",
                "model_source": "preset",
                "train_budget_mode": "target_updates",
                "target_updates": -1,
            }
        )
    with pytest.raises(ValueError, match="min_epochs must be <= max_epochs"):
        service.resolve_config(
            {
                "yolo_task": "detect",
                "model_source": "preset",
                "train_budget_mode": "target_updates",
                "target_updates": 100,
                "min_epochs": 30,
                "max_epochs": 20,
            }
        )

    cfg = service.resolve_config(
        {
            "yolo_task": "detect",
            "model_source": "preset",
            "train_budget_mode": "target_updates",
            "target_updates": 3000,
            "min_epochs": 20,
            "max_epochs": 300,
            "budget_disable_early_stop": False,
        }
    )
    assert str(getattr(cfg, "train_budget_mode", "")) == "target_updates"
    assert int(getattr(cfg, "target_updates", 0)) == 3000
    assert int(getattr(cfg, "min_epochs", 0)) == 20
    assert int(getattr(cfg, "max_epochs", 0)) == 300
    assert bool(getattr(cfg, "budget_disable_early_stop", True)) is False


def test_config_service_init_mode_defaults_to_checkpoint_direct():
    service = YoloConfigService()
    cfg = service.resolve_config(
        {
            "yolo_task": "detect",
            "model_source": "preset",
        }
    )
    assert str(getattr(cfg, "init_mode", "")) == "checkpoint_direct"
    assert str(getattr(cfg, "model_arch_source", "")) == "builtin"
    assert str(getattr(cfg, "model_arch_preset", "")) == ""
    assert str(getattr(cfg, "model_arch_custom_ref", "")) == ""


def test_config_service_arch_yaml_mode_infers_builtin_arch_from_preset():
    service = YoloConfigService()
    cfg = service.resolve_config(
        {
            "yolo_task": "detect",
            "model_source": "preset",
            "model_preset": "yolov8m.pt",
            "init_mode": "arch_yaml_plus_weights",
            "model_arch_source": "builtin",
        }
    )
    assert str(getattr(cfg, "init_mode", "")) == "arch_yaml_plus_weights"
    assert str(getattr(cfg, "model_arch_source", "")) == "builtin"
    assert str(getattr(cfg, "model_arch_preset", "")) == "yolov8m.yaml"


def test_config_service_arch_yaml_mode_requires_explicit_preset_when_cannot_infer():
    service = YoloConfigService()
    with pytest.raises(ValueError, match="model_arch_preset is required"):
        service.resolve_config(
            {
                "yolo_task": "detect",
                "model_source": "custom_local",
                "model_custom_ref": "/tmp/yolov8m_backbone.pt",
                "init_mode": "arch_yaml_plus_weights",
                "model_arch_source": "builtin",
            }
        )


def test_config_service_arch_yaml_mode_validates_custom_yaml_path(tmp_path: Path):
    service = YoloConfigService()
    yaml_path = tmp_path / "custom_arch.yaml"
    yaml_path.write_text("nc: 1\n", encoding="utf-8")
    cfg = service.resolve_config(
        {
            "yolo_task": "detect",
            "model_source": "custom_local",
            "model_custom_ref": str(tmp_path / "weights.pt"),
            "init_mode": "arch_yaml_plus_weights",
            "model_arch_source": "custom_local",
            "model_arch_custom_ref": str(yaml_path),
        }
    )
    assert str(getattr(cfg, "model_arch_source", "")) == "custom_local"
    assert str(getattr(cfg, "model_arch_custom_ref", "")) == str(yaml_path)


@pytest.mark.anyio
async def test_config_service_resolve_arch_yaml_ref_uses_builtin_inferred_preset():
    service = YoloConfigService()
    arch_ref = await service.resolve_arch_yaml_ref(
        workspace=Workspace("/tmp/unused", "unused"),
        params={
            "yolo_task": "obb",
            "model_source": "preset",
            "model_preset": "yolov8s-obb.pt",
            "init_mode": "arch_yaml_plus_weights",
            "model_arch_source": "builtin",
        },
    )
    assert arch_ref == "yolov8s-obb.yaml"


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
            epochs=17,
            batch=1,
            imgsz=640,
            patience=18,
            device="cpu",
            requested_device="auto",
            resolved_backend="cpu",
            resolved_base_model="yolov8n.pt",
            train_seed=22,
            deterministic=False,
            strong_deterministic=False,
            yolo_task="detect",
            requested_epochs=300,
            train_budget_mode="target_updates",
            target_updates=3000,
            min_epochs=20,
            max_epochs=300,
            budget_disable_early_stop=True,
            train_sample_count=17,
            steps_per_epoch=17,
            effective_epochs=17,
            effective_patience=18,
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
    assert any("训练预算解析完成" in msg for msg in emitted_logs)
    assert any("effective_epochs=17" in msg for msg in emitted_logs)
    report_payload = json.loads((workspace.artifacts_dir / "report.json").read_text(encoding="utf-8"))
    budget_summary = report_payload["metric_meta"]["budget_summary"]
    assert budget_summary == {
        "mode": "target_updates",
        "requested_epochs": 300,
        "target_updates": 3000,
        "train_sample_count": 17,
        "batch": 1,
        "steps_per_epoch": 17,
        "effective_epochs": 17,
        "effective_patience": 18,
    }


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


@pytest.mark.anyio
async def test_predict_service_uncertainty_accepts_suffixless_local_path(tmp_path: Path):
    from types import SimpleNamespace
    from PIL import Image as PILImage

    class _ConfigStub:
        def resolve_config(self, _params: dict[str, Any], **_kwargs: Any):
            return SimpleNamespace(
                topk=10,
                sampling_topk=10,
                predict_conf=0.1,
                imgsz=640,
                sampling_seed=7,
                random_seed=7,
                round_index=1,
            )

        async def resolve_model_ref(self, *, workspace: WorkspaceProtocol, params: Any):
            del params
            return str(workspace.artifacts_dir / "best.pt")

    model_holder: dict[str, Any] = {}

    class _Array:
        def __init__(self, values):
            self._values = values

        def cpu(self):
            return self

        def tolist(self):
            return list(self._values)

    class _Boxes:
        def __init__(self):
            self.cls = _Array([0])
            self.conf = _Array([0.77])
            self.xyxy = _Array([[2.0, 3.0, 8.0, 9.0]])

        def __len__(self):
            return 1

    class _Result:
        def __init__(self):
            self.boxes = _Boxes()
            self.names = {0: "obj"}

    def _load_yolo():
        class _FakeYOLO:
            def __init__(self, _model_path: str):
                self.sources: list[Any] = []
                self.batches: list[int] = []
                model_holder["model"] = self

            def predict(self, *, source, conf, imgsz, device, verbose, batch):
                del conf, imgsz, device, verbose
                self.sources.append(source)
                self.batches.append(batch)
                return [_Result()]

        return _FakeYOLO

    service = YoloPredictService(
        stop_flag=__import__("threading").Event(),
        config_service=_ConfigStub(),
        load_yolo=_load_yolo,
    )
    workspace = Workspace(str(tmp_path / "runs"), "step-yolo-uncertainty")
    workspace.ensure()
    (workspace.artifacts_dir / "best.pt").write_bytes(b"model")

    image_path = tmp_path / "assets" / "hash_without_ext"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (16, 16), color=(200, 10, 10)).save(image_path, format="PNG")

    context = ExecutionBindingContext(
        task_context=TaskRuntimeContext(
            task_id="task-yolo-uncertainty",
            round_id="round-1",
            round_index=1,
            attempt=1,
            task_type="score",
            mode="active_learning",
            split_seed=1,
            train_seed=2,
            sampling_seed=3,
            resolved_device_backend="cpu",
        ),
        host_capability=HostCapabilitySnapshot.from_dict(
            {
                "cpu_workers": 8,
                "memory_mb": 4096,
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

    rows = await service.predict_unlabeled_batch(
        workspace=workspace,
        unlabeled_samples=[{"id": "s1", "local_path": str(image_path)}],
        strategy="uncertainty_1_minus_max_conf",
        params={},
        context=context,
    )
    assert len(rows) == 1
    model = model_holder.get("model")
    assert model is not None
    assert model.sources
    assert model.sources[0] == [str(image_path)]
    assert model.batches == [1]


@pytest.mark.anyio
async def test_predict_service_direct_predict_accepts_suffixless_local_path(tmp_path: Path):
    from types import SimpleNamespace
    from PIL import Image as PILImage

    class _ConfigStub:
        def resolve_config(self, _params: dict[str, Any], **_kwargs: Any):
            return SimpleNamespace(
                predict_conf=0.1,
                imgsz=640,
                sampling_seed=7,
                round_index=1,
            )

        async def resolve_model_ref(self, *, workspace: WorkspaceProtocol, params: Any):
            del params
            return str(workspace.artifacts_dir / "best.pt")

    model_holder: dict[str, Any] = {}

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
            self.conf = _Array([0.66])
            self.xyxy = _Array([[1.0, 2.0, 9.0, 10.0]])

        def __len__(self):
            return 1

    class _Result:
        def __init__(self):
            self.boxes = _Boxes()
            self.names = {1: "target"}

    def _load_yolo():
        class _FakeYOLO:
            def __init__(self, _model_path: str):
                self.sources: list[Any] = []
                self.batches: list[int] = []
                model_holder["model"] = self

            def predict(self, *, source, conf, imgsz, device, verbose, batch):
                del conf, imgsz, device, verbose
                self.sources.append(source)
                self.batches.append(batch)
                return [_Result()]

        return _FakeYOLO

    service = YoloPredictService(
        stop_flag=__import__("threading").Event(),
        config_service=_ConfigStub(),
        load_yolo=_load_yolo,
    )
    workspace = Workspace(str(tmp_path / "runs"), "step-yolo-predict")
    workspace.ensure()
    (workspace.artifacts_dir / "best.pt").write_bytes(b"model")

    image_path = tmp_path / "assets" / "hash_without_ext_predict"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (12, 12), color=(10, 160, 10)).save(image_path, format="PNG")

    context = ExecutionBindingContext(
        task_context=TaskRuntimeContext(
            task_id="task-yolo-predict",
            round_id="round-1",
            round_index=1,
            attempt=1,
            task_type="predict",
            mode="manual",
            split_seed=1,
            train_seed=2,
            sampling_seed=3,
            resolved_device_backend="cpu",
        ),
        host_capability=HostCapabilitySnapshot.from_dict(
            {
                "cpu_workers": 8,
                "memory_mb": 4096,
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

    rows = await service.predict_samples_batch(
        workspace=workspace,
        samples=[{"id": "s2", "local_path": str(image_path)}],
        params={},
        context=context,
    )
    assert len(rows) == 1
    snapshot = rows[0].get("prediction_snapshot") or {}
    base_predictions = snapshot.get("base_predictions") if isinstance(snapshot, dict) else []
    assert isinstance(base_predictions, list)
    assert base_predictions
    model = model_holder.get("model")
    assert model is not None
    assert model.sources
    assert model.sources[0] == [str(image_path)]
    assert model.batches == [1]


@pytest.mark.anyio
async def test_predict_service_direct_predict_batches_multiple_samples(tmp_path: Path):
    from types import SimpleNamespace
    from PIL import Image as PILImage

    class _ConfigStub:
        def resolve_config(self, _params: dict[str, Any], **_kwargs: Any):
            return SimpleNamespace(
                predict_conf=0.1,
                imgsz=640,
                batch=16,
            )

        async def resolve_model_ref(self, *, workspace: WorkspaceProtocol, params: Any):
            del params
            return str(workspace.artifacts_dir / "best.pt")

    model_holder: dict[str, Any] = {}

    class _Array:
        def __init__(self, values):
            self._values = values

        def cpu(self):
            return self

        def tolist(self):
            return list(self._values)

    class _Boxes:
        def __init__(self, idx: int):
            self.cls = _Array([0])
            self.conf = _Array([0.6 + (idx * 0.1)])
            self.xyxy = _Array([[1.0, 2.0, 9.0 + idx, 10.0 + idx]])

        def __len__(self):
            return 1

    class _Result:
        def __init__(self, idx: int):
            self.boxes = _Boxes(idx)
            self.names = {0: "target"}

    def _load_yolo():
        class _FakeYOLO:
            def __init__(self, _model_path: str):
                self.sources: list[Any] = []
                self.batches: list[int] = []
                model_holder["model"] = self

            def predict(self, *, source, conf, imgsz, device, verbose, batch):
                del conf, imgsz, device, verbose
                self.sources.append(source)
                self.batches.append(batch)
                return [_Result(idx) for idx, _item in enumerate(source)]

        return _FakeYOLO

    service = YoloPredictService(
        stop_flag=__import__("threading").Event(),
        config_service=_ConfigStub(),
        load_yolo=_load_yolo,
    )
    workspace = Workspace(str(tmp_path / "runs"), "step-yolo-predict-batch")
    workspace.ensure()
    (workspace.artifacts_dir / "best.pt").write_bytes(b"model")

    samples: list[dict[str, Any]] = []
    for idx in range(3):
        image_path = tmp_path / "assets" / f"predict_batch_{idx}.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        PILImage.new("RGB", (16, 16), color=(10 + idx, 120, 30)).save(image_path)
        samples.append({"id": f"s{idx}", "local_path": str(image_path)})

    context = ExecutionBindingContext(
        task_context=TaskRuntimeContext(
            task_id="task-yolo-predict-batch",
            round_id="round-1",
            round_index=1,
            attempt=1,
            task_type="predict",
            mode="manual",
            split_seed=1,
            train_seed=2,
            sampling_seed=3,
            resolved_device_backend="cpu",
        ),
        host_capability=HostCapabilitySnapshot.from_dict(
            {
                "cpu_workers": 8,
                "memory_mb": 4096,
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

    rows = await service.predict_samples_batch(
        workspace=workspace,
        samples=samples,
        params={},
        context=context,
    )

    assert len(rows) == 3
    model = model_holder.get("model")
    assert model is not None
    assert model.sources == [[sample["local_path"] for sample in samples]]
    assert model.batches == [3]


@pytest.mark.anyio
async def test_predict_service_predict_samples_keeps_full_prediction_snapshot(tmp_path: Path):
    from types import SimpleNamespace
    from PIL import Image as PILImage

    class _ConfigStub:
        def resolve_config(self, _params: dict[str, Any], **_kwargs: Any):
            return SimpleNamespace(
                predict_conf=0.1,
                imgsz=640,
            )

        async def resolve_model_ref(self, *, workspace: WorkspaceProtocol, params: Any):
            del params
            return str(workspace.artifacts_dir / "best.pt")

    class _Array:
        def __init__(self, values):
            self._values = values

        def cpu(self):
            return self

        def tolist(self):
            return list(self._values)

    class _Boxes:
        def __init__(self):
            self.cls = _Array([0 for _ in range(35)])
            self.conf = _Array([0.5 + (idx * 0.01) for idx in range(35)])
            self.xyxy = _Array(
                [
                    [float(idx), float(idx + 1), float(idx + 2), float(idx + 3)]
                    for idx in range(35)
                ]
            )

        def __len__(self):
            return 35

    class _Result:
        def __init__(self):
            self.boxes = _Boxes()
            self.names = {0: "target"}

    def _load_yolo():
        class _FakeYOLO:
            def __init__(self, _model_path: str):
                pass

            def predict(self, *, source, conf, imgsz, device, verbose, batch):
                del source, conf, imgsz, device, verbose
                assert batch == 1
                return [_Result()]

        return _FakeYOLO

    service = YoloPredictService(
        stop_flag=__import__("threading").Event(),
        config_service=_ConfigStub(),
        load_yolo=_load_yolo,
    )
    workspace = Workspace(str(tmp_path / "runs"), "step-yolo-predict-full-snapshot")
    workspace.ensure()
    (workspace.artifacts_dir / "best.pt").write_bytes(b"model")

    image_path = tmp_path / "assets" / "hash_without_ext_predict_many"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (20, 20), color=(10, 20, 200)).save(image_path, format="PNG")

    context = ExecutionBindingContext(
        task_context=TaskRuntimeContext(
            task_id="task-yolo-predict-full-snapshot",
            round_id="round-1",
            round_index=1,
            attempt=1,
            task_type="predict",
            mode="manual",
            split_seed=1,
            train_seed=2,
            sampling_seed=3,
            resolved_device_backend="cpu",
        ),
        host_capability=HostCapabilitySnapshot.from_dict(
            {
                "cpu_workers": 8,
                "memory_mb": 4096,
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

    rows = await service.predict_samples_batch(
        workspace=workspace,
        samples=[{"id": "s3", "local_path": str(image_path)}],
        params={},
        context=context,
    )
    assert len(rows) == 1
    snapshot = rows[0].get("prediction_snapshot") or {}
    base_predictions = snapshot.get("base_predictions") if isinstance(snapshot, dict) else []
    assert isinstance(base_predictions, list)
    assert len(base_predictions) == 35
