from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest


def test_build_mmrotate_command_uses_generated_config_contract(
    tmp_path: Path,
) -> None:
    from obb_baseline.runners_mmrotate import build_mmrotate_train_command

    signature = inspect.signature(build_mmrotate_train_command)
    assert tuple(signature.parameters) == (
        "model_name",
        "run_dir",
        "generated_config",
        "work_dir",
        "train_seed",
        "device",
    )

    generated_config = tmp_path / "configs" / "oriented_rcnn.py"
    command = build_mmrotate_train_command(
        model_name="oriented_rcnn_r50",
        run_dir=tmp_path / "runs" / "oriented_rcnn_r50",
        generated_config=generated_config,
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
    assert str(generated_config) in command
    assert "--work-dir" in command
    assert str(tmp_path / "records" / "oriented_rcnn_r50" / "split-11" / "seed-101") in command
    assert "--seed" in command
    assert "101" in command
    assert "--device" in command
    assert "cuda:0" in command


@pytest.mark.parametrize(
    ("model_name", "expected_preset", "expected_base_marker"),
    [
        (
            "oriented_rcnn_r50",
            "oriented_rcnn",
            "oriented_rcnn/oriented-rcnn-le90_r50_fpn_1x_dota.py",
        ),
        (
            "roi_transformer_r50",
            "roi_transformer",
            "roi_trans/roi-trans-le90_r50_fpn_1x_dota.py",
        ),
        ("r3det_r50", "r3det", "r3det/r3det-oc_r50_fpn_1x_dota.py"),
        (
            "rtmdet_rotated_m",
            "rtmdet_rotated",
            "rotated_rtmdet/rotated_rtmdet_m-3x-dota.py",
        ),
    ],
)
def test_render_mmrotate_config_supports_all_presets(
    tmp_path: Path,
    model_name: str,
    expected_preset: str,
    expected_base_marker: str,
) -> None:
    from obb_baseline.runners_mmrotate import render_mmrotate_config

    signature = inspect.signature(render_mmrotate_config)
    assert "classes" in signature.parameters
    assert "class_names" not in signature.parameters

    config_text = render_mmrotate_config(
        model_name=model_name,
        data_root=tmp_path / "dataset",
        work_dir=tmp_path / "workdirs" / model_name / "split-11" / "seed-101",
        train_seed=101,
        score_thr=0.25,
        classes=("plane", "ship"),
    )

    assert f'preset = "{expected_preset}"' in config_text
    assert expected_base_marker in config_text
    assert f'data_root = r"{(tmp_path / "dataset").as_posix()}"' in config_text
    assert (
        f'work_dir = r"{(tmp_path / "workdirs" / model_name / "split-11" / "seed-101").as_posix()}"'
        in config_text
    )
    assert "train_seed = 101" in config_text
    assert "score_thr = 0.25" in config_text
    assert "classes = ('plane', 'ship')" in config_text
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


def test_write_mmrotate_metrics_json_writes_full_metric_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from obb_baseline.runners_mmrotate import (
        RunMetadata,
        write_mmrotate_metrics_json,
    )

    signature = inspect.signature(write_mmrotate_metrics_json)
    assert "normalized_metrics" in signature.parameters
    assert "metrics" not in signature.parameters

    def _should_not_be_called(_: object) -> dict[str, float | None]:
        raise AssertionError("writer should not call normalize_mmrotate_metrics")

    monkeypatch.setattr(
        "obb_baseline.runners_mmrotate.normalize_mmrotate_metrics",
        _should_not_be_called,
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
        normalized_metrics={
            "mAP50_95": "keep-this-raw",
            "mAP50": 0.62,
            "precision": 0.8,
            "recall": 0.5,
            "f1": 0.615384,
        },
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
    assert payload["mAP50_95"] == "keep-this-raw"
    assert payload["mAP50"] == 0.62
    assert payload["precision"] == 0.8
    assert payload["recall"] == 0.5
    assert payload["f1"] == 0.615384
    assert payload["train_time_sec"] == 123.4
    assert payload["infer_time_ms"] == 7.8
    assert payload["peak_mem_mb"] == 4096.0
    assert payload["param_count"] == 20500000
    assert payload["checkpoint_size_mb"] == 82.1
    assert payload["artifact_paths"] == {
        "config": "configs/oriented_rcnn.py",
        "best_checkpoint": "checkpoints/best.pth",
    }


def test_main_executes_pipeline_and_writes_stable_raw_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from obb_baseline import runners_mmrotate as module

    generated_config = tmp_path / "generated.py"
    generated_config.write_text(
        (
            'preset = "oriented_rcnn"\n'
            "classes = ('plane', 'ship')\n"
            "class_names = classes\n"
            "num_classes = len(classes)\n"
        ),
        encoding="utf-8",
    )
    work_dir = tmp_path / "work"

    captured: dict[str, object] = {}

    def _fake_execute(
        *,
        generated_config: Path,
        parsed_generated_config: dict[str, object],
        work_dir: Path,
        train_seed: int,
        device: str,
    ) -> dict[str, dict[str, object]]:
        captured["generated_config"] = generated_config
        captured["parsed_generated_config"] = parsed_generated_config
        captured["work_dir"] = work_dir
        captured["train_seed"] = train_seed
        captured["device"] = device
        return {
            "raw_metrics": {"dota/mAP": 0.42, "dota/AP50": 0.66},
            "artifacts": {"best_checkpoint": "epoch_12.pth"},
        }

    monkeypatch.setattr(module, "_execute_mmrotate_pipeline", _fake_execute)

    exit_code = module.main(
        [
            "--config",
            str(generated_config),
            "--work-dir",
            str(work_dir),
            "--seed",
            "101",
            "--device",
            "cpu",
        ]
    )

    assert exit_code == 0
    assert captured["generated_config"] == generated_config
    assert captured["work_dir"] == work_dir
    assert captured["train_seed"] == 101
    assert captured["device"] == "cpu"
    assert captured["parsed_generated_config"] == {
        "preset": "oriented_rcnn",
        "classes": ("plane", "ship"),
        "class_names": ("plane", "ship"),
        "num_classes": 2,
    }

    raw_metrics_path = work_dir / "raw_metrics.json"
    artifacts_path = work_dir / "artifacts.json"
    assert raw_metrics_path.exists()
    assert artifacts_path.exists()
    assert json.loads(raw_metrics_path.read_text(encoding="utf-8")) == {"dota/mAP": 0.42, "dota/AP50": 0.66}
    assert json.loads(artifacts_path.read_text(encoding="utf-8")) == {"best_checkpoint": "epoch_12.pth"}


def test_main_writes_raw_outputs_with_numpy_like_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from obb_baseline import runners_mmrotate as module

    class FakeScalar:
        def __init__(self, value: object) -> None:
            self.value = value

        def item(self) -> object:
            return self.value

    class FakeArray:
        def __init__(self, values: list[object]) -> None:
            self.values = values

        def tolist(self) -> list[object]:
            return list(self.values)

    generated_config = tmp_path / "generated.py"
    generated_config.write_text(
        (
            'preset = "oriented_rcnn"\n'
            "classes = ('plane', 'ship')\n"
            "class_names = classes\n"
            "num_classes = len(classes)\n"
        ),
        encoding="utf-8",
    )
    work_dir = tmp_path / "work"

    def _fake_execute(
        *,
        generated_config: Path,
        parsed_generated_config: dict[str, object],
        work_dir: Path,
        train_seed: int,
        device: str,
    ) -> dict[str, dict[str, object]]:
        _ = (
            generated_config,
            parsed_generated_config,
            work_dir,
            train_seed,
            device,
        )
        return {
            "raw_metrics": {
                "dota/mAP": FakeScalar(0.42),
                "curve": FakeArray([FakeScalar(1), FakeScalar(2)]),
                "summary_path": Path("metrics/summary.txt"),
                "scores": (FakeScalar(0.1), FakeScalar(0.2)),
            },
            "artifacts": {
                "best_checkpoint": Path("epoch_12.pth"),
                "history": FakeArray([FakeScalar(3), FakeScalar(4)]),
            },
        }

    monkeypatch.setattr(module, "_execute_mmrotate_pipeline", _fake_execute)

    exit_code = module.main(
        [
            "--config",
            str(generated_config),
            "--work-dir",
            str(work_dir),
            "--seed",
            "101",
            "--device",
            "cpu",
        ]
    )

    assert exit_code == 0
    raw_metrics_path = work_dir / "raw_metrics.json"
    artifacts_path = work_dir / "artifacts.json"
    assert json.loads(raw_metrics_path.read_text(encoding="utf-8")) == {
        "dota/mAP": 0.42,
        "curve": [1, 2],
        "summary_path": "metrics/summary.txt",
        "scores": [0.1, 0.2],
    }
    assert json.loads(artifacts_path.read_text(encoding="utf-8")) == {
        "best_checkpoint": "epoch_12.pth",
        "history": [3, 4],
    }
