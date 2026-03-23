from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = (Path(__file__).resolve().parents[1] / "scripts" / "split_dataset.py").resolve()


def test_split_dataset_cli_writes_manifest_and_summary(tmp_path, tiny_dota_export) -> None:
    out_dir = tmp_path / "runs" / "obb_baseline" / "smoke_split"
    cmd = [
        sys.executable,
        str(SCRIPT_PATH),
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
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)

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
        str(SCRIPT_PATH),
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
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)

    manifest = json.loads((out_dir / "split_manifest.json").read_text(encoding="utf-8"))
    assert manifest["test_ratio"] == 0.15
    assert manifest["val_ratio"] == 0.15


def test_split_dataset_cli_runs_without_pythonpath(tmp_path, tiny_dota_export) -> None:
    out_dir = tmp_path / "runs" / "obb_baseline" / "no_pythonpath_split"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    cmd = [
        sys.executable,
        "-S",
        str(SCRIPT_PATH),
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
    subprocess.run(cmd, check=True, env=env, cwd=REPO_ROOT)
    assert (out_dir / "split_manifest.json").is_file()


def test_split_dataset_cli_keeps_symlink_dataset_name(tmp_path, tiny_dota_export) -> None:
    out_dir = tmp_path / "runs" / "obb_baseline" / "symlink_split"
    symlink_root = tmp_path / "alias_dota_export"
    try:
        symlink_root.symlink_to(tiny_dota_export, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink not supported: {exc}")
    cmd = [
        sys.executable,
        str(SCRIPT_PATH),
        "--dota-root",
        str(symlink_root),
        "--classes",
        "pattern_a,pattern_b,pattern_c",
        "--out-dir",
        str(out_dir),
        "--holdout-seed",
        "3407",
        "--split-seeds",
        "11",
    ]
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)

    manifest = json.loads((out_dir / "split_manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset_name"] == symlink_root.name


def test_split_dataset_cli_falls_back_to_adjacent_src(tmp_path, tiny_dota_export) -> None:
    local_root = tmp_path / "local_app"
    local_scripts = local_root / "scripts"
    local_src_root = local_root / "src"
    local_pkg_root = local_src_root / "obb_baseline"
    local_scripts.mkdir(parents=True)
    local_pkg_root.mkdir(parents=True)

    local_script = local_scripts / "split_dataset.py"
    local_script.write_text(SCRIPT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    source_pkg_root = SCRIPT_PATH.parents[1] / "src" / "obb_baseline"
    for source_path in source_pkg_root.rglob("*.py"):
        relative_path = source_path.relative_to(source_pkg_root)
        dest_path = local_pkg_root / relative_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")

    out_dir = tmp_path / "runs" / "obb_baseline" / "relocated_split"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    cmd = [
        sys.executable,
        "-S",
        str(local_script),
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
    subprocess.run(cmd, check=True, env=env, cwd=REPO_ROOT)
    assert (out_dir / "split_manifest.json").is_file()
