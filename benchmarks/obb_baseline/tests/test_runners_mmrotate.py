from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_build_mmrotate_command_uses_mmrotate_env_and_module_entrypoint(
    tmp_path: Path,
) -> None:
    from obb_baseline.runners_mmrotate import build_mmrotate_train_command

    command = build_mmrotate_train_command(
        config_path=tmp_path / "configs" / "oriented_rcnn.py",
        work_dir=tmp_path / "records" / "oriented_rcnn_r50" / "split-11" / "seed-101",
        train_seed=101,
        device="cuda:0",
    )

    assert command[:7] == [
        "uv",
        "run",
        "--project",
        "benchmarks/obb_baseline/envs/mmrotate",
        "python",
        "-m",
        "obb_baseline.runners_mmrotate",
    ]
    assert "--config" in command
    assert str(tmp_path / "configs" / "oriented_rcnn.py") in command
    assert "--work-dir" in command
    assert str(tmp_path / "records" / "oriented_rcnn_r50" / "split-11" / "seed-101") in command
    assert "--seed" in command
    assert "101" in command
    assert "--device" in command
    assert "cuda:0" in command


@pytest.mark.parametrize(
    ("model_name", "expected_marker"),
    [
        ("oriented_rcnn_r50", "oriented_rcnn"),
        ("roi_transformer_r50", "roi_transformer"),
        ("r3det_r50", "r3det"),
        ("rtmdet_rotated_m", "rtmdet_rotated"),
    ],
)
def test_render_mmrotate_config_supports_all_presets(
    tmp_path: Path,
    model_name: str,
    expected_marker: str,
) -> None:
    from obb_baseline.runners_mmrotate import render_mmrotate_config

    config_text = render_mmrotate_config(
        model_name=model_name,
        data_root=tmp_path / "dataset",
        work_dir=tmp_path / "workdirs" / model_name / "split-11" / "seed-101",
        train_seed=101,
        score_thr=0.25,
        class_names=("plane", "ship"),
    )

    assert f'base_preset = "{expected_marker}"' in config_text
    assert f'data_root = r"{(tmp_path / "dataset").as_posix()}"' in config_text
    assert (
        f'work_dir = r"{(tmp_path / "workdirs" / model_name / "split-11" / "seed-101").as_posix()}"'
        in config_text
    )
    assert "train_seed = 101" in config_text
    assert "score_thr = 0.25" in config_text
    assert "class_names = ('plane', 'ship')" in config_text
    assert "num_classes = 2" in config_text


def test_normalize_mmrotate_metrics_maps_dota_keys_and_computes_f1() -> None:
    from obb_baseline.runners_mmrotate import normalize_mmrotate_metrics

    metrics = normalize_mmrotate_metrics(
        {
            "dota/AP50": 0.62,
            "dota/mAP": "0.41",
            "precision": 0.8,
            "recall": "0.5",
        }
    )

    assert metrics == {
        "mAP50_95": 0.41,
        "mAP50": 0.62,
        "precision": 0.8,
        "recall": 0.5,
        "f1": pytest.approx(2 * 0.8 * 0.5 / (0.8 + 0.5), abs=1e-6),
    }


def test_write_mmrotate_metrics_json_writes_full_metric_contract(tmp_path: Path) -> None:
    from obb_baseline.runners_mmrotate import (
        RunMetadata,
        normalize_mmrotate_metrics,
        write_mmrotate_metrics_json,
    )

    metrics_path = tmp_path / "metrics.json"
    write_mmrotate_metrics_json(
        metrics_path=metrics_path,
        run_metadata=RunMetadata(
            benchmark_name="fedo_part2_v1",
            split_manifest_hash="abc123",
            model_name="oriented_rcnn_r50",
            preset="oriented-rcnn-r50-fpn",
            holdout_seed=3407,
            split_seed=11,
            train_seed=101,
            artifact_paths={
                "config": "configs/oriented_rcnn.py",
                "best_checkpoint": "checkpoints/best.pth",
            },
            train_time_sec=123.4,
            infer_time_ms=7.8,
            peak_mem_mb=4096.0,
            param_count=20500000,
            checkpoint_size_mb=82.1,
        ),
        status="succeeded",
        metrics=normalize_mmrotate_metrics(
            {
                "dota/AP50": 0.62,
                "dota/mAP": 0.41,
                "precision": 0.8,
                "recall": 0.5,
            }
        ),
    )

    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert set(payload) == {
        "benchmark_name",
        "split_manifest_hash",
        "model_name",
        "preset",
        "holdout_seed",
        "split_seed",
        "train_seed",
        "status",
        "mAP50_95",
        "mAP50",
        "precision",
        "recall",
        "f1",
        "train_time_sec",
        "infer_time_ms",
        "peak_mem_mb",
        "param_count",
        "checkpoint_size_mb",
        "artifact_paths",
    }
    assert payload["benchmark_name"] == "fedo_part2_v1"
    assert payload["split_manifest_hash"] == "abc123"
    assert payload["model_name"] == "oriented_rcnn_r50"
    assert payload["preset"] == "oriented-rcnn-r50-fpn"
    assert payload["holdout_seed"] == 3407
    assert payload["split_seed"] == 11
    assert payload["train_seed"] == 101
    assert payload["status"] == "succeeded"
    assert payload["mAP50_95"] == 0.41
    assert payload["mAP50"] == 0.62
    assert payload["precision"] == 0.8
    assert payload["recall"] == 0.5
    assert payload["f1"] == pytest.approx(2 * 0.8 * 0.5 / (0.8 + 0.5), abs=1e-6)
    assert payload["train_time_sec"] == 123.4
    assert payload["infer_time_ms"] == 7.8
    assert payload["peak_mem_mb"] == 4096.0
    assert payload["param_count"] == 20500000
    assert payload["checkpoint_size_mb"] == 82.1
    assert payload["artifact_paths"] == {
        "config": "configs/oriented_rcnn.py",
        "best_checkpoint": "checkpoints/best.pth",
    }
