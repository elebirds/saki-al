import asyncio
from pathlib import Path

import pytest

from saki_executor.plugins.builtin.yolo_det import plugin as yolo_plugin_module
from saki_executor.plugins.builtin.yolo_det.plugin import YoloDetectionPlugin
from saki_executor.steps.services.ir_dataset_builder import build_training_batch_ir
from saki_executor.steps.workspace import Workspace


def test_yolo_plugin_contract_fields():
    plugin = YoloDetectionPlugin()
    assert plugin.plugin_id == "yolo_det_v1"
    assert "train" in plugin.supported_step_types
    assert "aug_iou_disagreement" in plugin.supported_strategies
    assert "aug_iou_disagreement_v1" not in plugin.supported_strategies
    assert "plugin_native_strategy" not in plugin.supported_strategies


def test_yolo_plugin_validate_params():
    plugin = YoloDetectionPlugin()
    plugin.validate_params(
        {
            "epochs": 30,
            "batch": 16,
            "imgsz": 640,
            "model_source": "preset",
            "model_preset": "yolov8n-obb.pt",
        }
    )


def test_yolo_plugin_model_source_preset_default():
    plugin = YoloDetectionPlugin()
    resolved = plugin.resolve_config(
        mode="manual",
        raw_config={
            "model_source": "preset",
            "model_preset": "yolov8s-obb.pt",
        },
    )
    assert resolved["model_source"] == "preset"
    assert resolved["model_preset"] == "yolov8s-obb.pt"
    assert resolved["model_custom_ref"] == ""


def test_yolo_plugin_model_source_custom_local(tmp_path: Path):
    plugin = YoloDetectionPlugin()
    workspace = Workspace(str(tmp_path), "job-model-local")
    workspace.ensure()
    custom_model = tmp_path / "custom.pt"
    custom_model.write_bytes(b"pt")

    resolved = plugin.resolve_config(
        mode="manual",
        raw_config={
            "model_source": "custom_local",
            "model_custom_ref": str(custom_model),
        },
    )
    model_ref = asyncio.run(plugin._internal._resolve_model_ref(workspace=workspace, params=resolved))  # noqa: SLF001
    assert model_ref == str(custom_model)


def test_yolo_plugin_model_source_custom_url(tmp_path: Path, monkeypatch):
    plugin = YoloDetectionPlugin()
    workspace = Workspace(str(tmp_path), "job-model-url")
    workspace.ensure()

    async def _fake_download(url: str, target: Path) -> None:
        del url
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"remote-pt")

    monkeypatch.setattr(plugin._internal, "_download_to_file", _fake_download)  # noqa: SLF001
    resolved = plugin.resolve_config(
        mode="manual",
        raw_config={
            "model_source": "custom_url",
            "model_custom_ref": "https://example.com/model.pt",
        },
    )
    model_ref = asyncio.run(plugin._internal._resolve_model_ref(workspace=workspace, params=resolved))  # noqa: SLF001
    assert Path(model_ref).exists()
    assert Path(model_ref).read_bytes() == b"remote-pt"


def test_yolo_prepare_data_infers_hw_from_source_path(tmp_path: Path, monkeypatch):
    plugin = YoloDetectionPlugin()
    workspace = Workspace(str(tmp_path), "job-prepare")
    workspace.ensure()

    image_path = tmp_path / "sample.jpg"
    image_path.write_bytes(b"not-an-image-but-copyable")

    called: dict[str, Path] = {}

    def _fake_infer(path: Path) -> tuple[int, int]:
        called["path"] = Path(path)
        return 500, 1000

    monkeypatch.setattr(yolo_plugin_module, "_infer_image_hw", _fake_infer)

    labels = [{"id": "label-1", "name": "ship"}]
    samples_for_plugin = [{"id": "sample-1", "local_path": str(image_path), "width": 0, "height": 0}]
    samples_for_ir = [{"id": "sample-1", "local_path": str(image_path), "width": 1000, "height": 500}]
    annotations = [
        {
            "sample_id": "sample-1",
            "category_id": "label-1",
            "obb": {
                "cx": 500.0,
                "cy": 250.0,
                "width": 400.0,
                "height": 200.0,
                "angle_deg_ccw": 30.0,
            },
        }
    ]
    dataset_ir, _ = build_training_batch_ir(
        labels=labels,
        samples=samples_for_ir,
        annotations=annotations,
    )

    asyncio.run(plugin.prepare_data(workspace, labels, samples_for_plugin, annotations, dataset_ir=dataset_ir))
    assert called["path"] == image_path

    label_file = workspace.data_dir / "labels" / "train" / "sample-1.txt"
    assert label_file.exists()
    assert label_file.read_text(encoding="utf-8").strip()


def test_yolo_prepare_data_uses_ir_dataset_for_legacy_obb_payload(tmp_path: Path, monkeypatch):
    plugin = YoloDetectionPlugin()
    workspace = Workspace(str(tmp_path), "job-prepare-ir")
    workspace.ensure()

    image_path = tmp_path / "sample.jpg"
    image_path.write_bytes(b"not-an-image-but-copyable")

    def _fail_infer(path: Path) -> tuple[int, int]:
        raise AssertionError(f"unexpected infer call: {path}")

    monkeypatch.setattr(yolo_plugin_module, "_infer_image_hw", _fail_infer)

    labels = [{"id": "label-1", "name": "ship"}]
    samples = [{"id": "sample-1", "local_path": str(image_path), "width": 1000, "height": 500}]
    annotations = [
        {
            "sample_id": "sample-1",
            "category_id": "label-1",
            "obb": {
                "cx": 500.0,
                "cy": 250.0,
                "width": 400.0,
                "height": 200.0,
                "angle_deg_ccw": 30.0,
            },
        }
    ]
    dataset_ir, _ = build_training_batch_ir(
        labels=labels,
        samples=samples,
        annotations=annotations,
    )

    asyncio.run(plugin.prepare_data(workspace, labels, samples, annotations, dataset_ir=dataset_ir))

    label_file = workspace.data_dir / "labels" / "train" / "sample-1.txt"
    assert label_file.exists()
    values = label_file.read_text(encoding="utf-8").strip().split()
    assert len(values) == 9


def test_yolo_plugin_auto_device_falls_back_to_cpu(monkeypatch):
    plugin = YoloDetectionPlugin()
    params = {"device": "auto"}

    monkeypatch.setattr(
        "saki_executor.plugins.builtin.yolo_det.internal.probe_hardware",
        lambda **kwargs: {
            "gpu_count": 0,
            "gpu_device_ids": [],
            "cpu_workers": 1,
            "memory_mb": 0,
            "accelerators": [
                {"type": "cpu", "available": True, "device_count": 1, "device_ids": ["cpu"]},
            ],
        },
    )

    device, requested, resolved = plugin._internal._resolve_device(params)  # noqa: SLF001
    assert requested == "auto"
    assert resolved == "cpu"
    assert device == "cpu"
    assert params["_resolved_device_backend"] == "cpu"


def test_yolo_plugin_auto_device_prefers_cpu_over_mps(monkeypatch):
    plugin = YoloDetectionPlugin()
    params = {"device": "auto"}

    monkeypatch.setattr(
        "saki_executor.plugins.builtin.yolo_det.internal.probe_hardware",
        lambda **kwargs: {
            "gpu_count": 0,
            "gpu_device_ids": [],
            "cpu_workers": 1,
            "memory_mb": 0,
            "accelerators": [
                {"type": "mps", "available": True, "device_count": 1, "device_ids": ["mps"]},
                {"type": "cpu", "available": True, "device_count": 1, "device_ids": ["cpu"]},
            ],
        },
    )

    device, requested, resolved = plugin._internal._resolve_device(params)  # noqa: SLF001
    assert requested == "auto"
    assert resolved == "cpu"
    assert device == "cpu"
    assert params["_resolved_device_backend"] == "cpu"


def test_yolo_plugin_explicit_cuda_without_cuda_raises(monkeypatch):
    plugin = YoloDetectionPlugin()
    params = {"device": "0"}

    monkeypatch.setattr(
        "saki_executor.plugins.builtin.yolo_det.internal.probe_hardware",
        lambda **kwargs: {
            "gpu_count": 0,
            "gpu_device_ids": [],
            "cpu_workers": 1,
            "memory_mb": 0,
            "accelerators": [
                {"type": "cpu", "available": True, "device_count": 1, "device_ids": ["cpu"]},
            ],
        },
    )

    with pytest.raises(ValueError, match="Invalid CUDA"):
        plugin._internal._resolve_device(params)  # noqa: SLF001
