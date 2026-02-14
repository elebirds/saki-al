import asyncio
from pathlib import Path

import pytest

from saki_executor.plugins.builtin.yolo_det import plugin as yolo_plugin_module
from saki_executor.plugins.builtin.yolo_det.plugin import YoloDetectionPlugin
from saki_executor.steps.workspace import Workspace


def test_yolo_plugin_contract_fields():
    plugin = YoloDetectionPlugin()
    assert plugin.plugin_id == "yolo_det_v1"
    assert "train_detection" in plugin.supported_step_types
    assert "aug_iou_disagreement_v1" in plugin.supported_strategies


def test_yolo_plugin_validate_params():
    plugin = YoloDetectionPlugin()
    plugin.validate_params(
        {
            "epochs": 30,
            "batch": 16,
            "imgsz": 640,
            "topk": 200,
        }
    )


def test_yolo_plugin_parse_normalized_obb_payload():
    plugin = YoloDetectionPlugin()
    line = plugin._annotation_to_yolo_obb_line(  # noqa: SLF001
        ann={
            "obb": {
                "cx": 0.5,
                "cy": 0.5,
                "w": 0.4,
                "h": 0.2,
                "angle_deg": 30.0,
                "normalized": True,
            }
        },
        cls_idx=1,
        width=1000,
        height=500,
    )
    assert line is not None
    values = line.split()
    assert values[0] == "1"
    assert len(values) == 9


def test_yolo_plugin_rejects_legacy_obb_payload():
    plugin = YoloDetectionPlugin()
    line = plugin._annotation_to_yolo_obb_line(  # noqa: SLF001
        ann={
            "obb": {
                "cx": 0.5,
                "cy": 0.5,
                "width": 0.4,
                "height": 0.2,
                "angle": 30.0,
                "normalized": True,
            }
        },
        cls_idx=1,
        width=1000,
        height=500,
    )
    assert line is None


def test_yolo_plugin_resolve_split_seed_from_workspace_config(tmp_path: Path):
    plugin = YoloDetectionPlugin()
    workspace = Workspace(str(tmp_path), "job-1")
    workspace.ensure()
    workspace.write_config(
        {
            "loop_id": "11111111-1111-1111-1111-111111111111",
            "round_index": 3,
            "params": {"split_seed": 12345, "val_split_ratio": 0.25},
        }
    )
    split_seed, val_ratio = plugin._resolve_split_config(workspace)  # noqa: SLF001
    assert split_seed == 12345
    assert val_ratio == 0.25


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
    samples = [{"id": "sample-1", "local_path": str(image_path), "width": 0, "height": 0}]
    annotations = [
        {
            "sample_id": "sample-1",
            "category_id": "label-1",
            "obb": {
                "cx": 0.5,
                "cy": 0.5,
                "w": 0.4,
                "h": 0.2,
                "angle_deg": 30.0,
                "normalized": True,
            },
        }
    ]

    asyncio.run(plugin.prepare_data(workspace, labels, samples, annotations))
    assert called["path"] == image_path

    label_file = workspace.data_dir / "labels" / "train" / "sample-1.txt"
    assert label_file.exists()
    assert label_file.read_text(encoding="utf-8").strip()


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
