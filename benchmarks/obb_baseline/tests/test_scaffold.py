from __future__ import annotations

from pathlib import Path

EXPECTED_FILES = [
    "benchmarks/obb_baseline/README.md",
    "benchmarks/obb_baseline/configs/benchmark.fedo_part2_v1.yaml",
    "benchmarks/obb_baseline/configs/benchmark.fedo_part3_orcnn_v1.yaml",
    "benchmarks/obb_baseline/configs/models.yaml",
    "benchmarks/obb_baseline/scripts/split_dataset.py",
    "benchmarks/obb_baseline/scripts/run_suite.py",
    "benchmarks/obb_baseline/src/obb_baseline/__init__.py",
    "benchmarks/obb_baseline/tests/conftest.py",
]


def test_benchmark_skeleton_files_exist() -> None:
    root = Path(__file__).resolve().parents[3]
    missing = [path for path in EXPECTED_FILES if not (root / path).is_file()]
    assert not missing, f"缺少基准骨架文件: {missing}"
