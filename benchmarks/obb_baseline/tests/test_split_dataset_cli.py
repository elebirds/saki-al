from __future__ import annotations

import json
import subprocess
import sys


def test_split_dataset_cli_writes_manifest_and_summary(tmp_path, tiny_dota_export) -> None:
    out_dir = tmp_path / "runs" / "obb_baseline" / "smoke_split"
    cmd = [
        sys.executable,
        "benchmarks/obb_baseline/scripts/split_dataset.py",
        "--dota-root",
        str(tiny_dota_export),
        "--classes",
        "pattern_a,pattern_b,pattern_c",
        "--out-dir",
        str(out_dir),
        "--holdout-seed",
        "3407",
        "--split-seeds",
        "11,17,23",
    ]
    subprocess.run(cmd, check=True)

    manifest = json.loads((out_dir / "split_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((out_dir / "split_summary.json").read_text(encoding="utf-8"))
    assert manifest["dataset_name"] == tiny_dota_export.name
    assert manifest["holdout_seed"] == 3407
    assert manifest["split_seeds"] == [11, 17, 23]
    assert set(manifest["splits"]["11"]) == {"train_ids", "val_ids", "test_ids"}
    assert manifest["splits"]["11"]["test_ids"] == manifest["splits"]["17"]["test_ids"]
    assert summary["split_count"] == 3
    assert "class_mask_distribution" in summary["splits"]["11"]


def test_split_dataset_cli_uses_default_ratios_when_not_overridden(
    tmp_path, tiny_dota_export
) -> None:
    out_dir = tmp_path / "runs" / "obb_baseline" / "default_ratio_split"
    cmd = [
        sys.executable,
        "benchmarks/obb_baseline/scripts/split_dataset.py",
        "--dota-root",
        str(tiny_dota_export),
        "--classes",
        "pattern_a,pattern_b,pattern_c",
        "--out-dir",
        str(out_dir),
        "--holdout-seed",
        "3407",
        "--split-seeds",
        "11",
    ]
    subprocess.run(cmd, check=True)

    manifest = json.loads((out_dir / "split_manifest.json").read_text(encoding="utf-8"))
    assert manifest["test_ratio"] == 0.15
    assert manifest["val_ratio"] == 0.15
