from __future__ import annotations

from pathlib import Path

import yaml

EXPECTED_FILES = [
    "benchmarks/obb_baseline/README.md",
    "benchmarks/obb_baseline/configs/benchmark.fedo_part2_v1.yaml",
    "benchmarks/obb_baseline/configs/benchmark.fedo_part3_orcnn_v1.yaml",
    "benchmarks/obb_baseline/configs/models.yaml",
    "benchmarks/obb_baseline/scripts/split_dataset.py",
    "benchmarks/obb_baseline/scripts/run_suite.py",
    "benchmarks/obb_baseline/src/obb_baseline/__init__.py",
    "benchmarks/obb_baseline/tests/conftest.py",
    "benchmarks/obb_baseline/tests/test_scaffold.py",
]


def test_benchmark_skeleton_files_exist() -> None:
    root = Path(__file__).resolve().parents[3]
    missing = [path for path in EXPECTED_FILES if not (root / path).is_file()]
    assert not missing, f"缺少基准骨架文件: {missing}"


def test_models_config_includes_model_skeletons() -> None:
    root = Path(__file__).resolve().parents[3]
    config_path = root / "benchmarks/obb_baseline/configs/models.yaml"
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    assert isinstance(config, dict), "models.yaml 应返回映射"
    models = config.get("models")
    assert isinstance(models, dict), "models.yaml 缺少 models 字段"

    expected_models = {
        "yolo11m_obb",
        "yolov8m_obb",
        "yolo26m_obb",
        "oriented_rcnn_r50",
        "roi_transformer_r50",
        "r3det_r50",
        "rtmdet_rotated_m",
    }
    missing_models = expected_models - set(models)
    assert not missing_models, "models.yaml 需要声明全部基准模型"

    required_fields = {"runner", "env", "data_view", "preset"}
    for name, entry in models.items():
        assert isinstance(entry, dict), f"{name} 的配置应该是映射"
        missing = required_fields - set(entry.keys())
        assert not missing, f"{name} 缺少字段: {sorted(missing)}"
