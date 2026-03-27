from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_build_yolo_command_uses_yolo_env_and_dataset_yaml(tmp_path: Path) -> None:
    from obb_baseline.runners_yolo import build_yolo_train_command

    command = build_yolo_train_command(
        preset="yolo11m-obb",
        dataset_yaml=tmp_path / "dataset.yaml",
        run_dir=tmp_path / "records" / "yolo11m_obb" / "split-11" / "seed-101",
        work_dir=tmp_path / "workdirs" / "yolo11m_obb" / "split-11" / "seed-101",
        train_seed=101,
        device="0",
        imgsz=960,
        epochs=36,
        batch_size=2,
        workers=6,
        amp=False,
        mosaic=0.0,
        close_mosaic=0,
    )
    assert command[:4] == [
        "uv",
        "run",
        "--project",
        "benchmarks/obb_baseline/envs/yolo",
    ]
    assert command[4:6] == ["yolo", "train"]
    assert "train" in command
    assert "task=obb" in command
    assert "model=yolo11m-obb" in command
    assert f"data={tmp_path / 'dataset.yaml'}" in command
    assert f"project={tmp_path / 'workdirs' / 'yolo11m_obb' / 'split-11'}" in command
    assert "name=seed-101" in command
    assert "exist_ok=True" in command
    assert "seed=101" in command
    assert "device=0" in command
    assert "imgsz=960" in command
    assert "epochs=36" in command
    assert "batch=2" in command
    assert "workers=6" in command
    assert "amp=False" in command
    assert "mosaic=0.0" in command
    assert "close_mosaic=0" in command


def test_build_yolo_test_command_uses_best_checkpoint_and_test_split(tmp_path: Path) -> None:
    from obb_baseline.runners_yolo import build_yolo_test_command

    command = build_yolo_test_command(
        checkpoint_path=tmp_path / "weights" / "best.pt",
        dataset_yaml=tmp_path / "dataset.yaml",
        work_dir=tmp_path / "workdirs" / "yolo11m_obb" / "split-11" / "seed-101",
        device="0",
        imgsz=960,
        batch_size=8,
        workers=4,
    )

    assert command[:4] == [
        "uv",
        "run",
        "--project",
        "benchmarks/obb_baseline/envs/yolo",
    ]
    assert command[4:6] == ["yolo", "val"]
    assert f"model={tmp_path / 'weights' / 'best.pt'}" in command
    assert f"data={tmp_path / 'dataset.yaml'}" in command
    assert "task=obb" in command
    assert "split=test" in command
    assert f"project={tmp_path / 'workdirs' / 'yolo11m_obb' / 'split-11' / 'seed-101'}" in command
    assert "name=test_eval" in command
    assert "device=0" in command
    assert "imgsz=960" in command
    assert "batch=8" in command
    assert "workers=4" in command


def test_parse_yolo_results_csv_returns_full_metric_contract(tmp_path: Path) -> None:
    from obb_baseline.runners_yolo import parse_yolo_results_csv

    results_csv = tmp_path / "results.csv"
    results_csv.write_text(
        "metrics/mAP50(B),metrics/mAP50-95(B),metrics/precision(B),metrics/recall(B)\n"
        "0.7,0.4,0.8,0.6\n",
        encoding="utf-8",
    )
    metrics = parse_yolo_results_csv(results_csv)
    assert metrics["mAP50"] == 0.7
    assert metrics["mAP50_95"] == 0.4
    assert metrics["precision"] == 0.8
    assert metrics["recall"] == 0.6


def test_write_yolo_metrics_json_writes_full_metric_contract(tmp_path: Path) -> None:
    from obb_baseline.runners_yolo import RunMetadata, write_yolo_metrics_json

    results_csv = tmp_path / "results.csv"
    results_csv.write_text(
        "metrics/mAP50(B),metrics/mAP50-95(B),metrics/precision(B),metrics/recall(B)\n"
        "0.7,0.4,0.8,0.6\n",
        encoding="utf-8",
    )
    metrics_path = tmp_path / "metrics.json"
    write_yolo_metrics_json(
        results_csv=results_csv,
        metrics_path=metrics_path,
        run_metadata=RunMetadata(
            benchmark_name="fedo_part2_v1",
            split_manifest_hash="abc123",
            model_name="yolo11m_obb",
            preset="yolo11m-obb",
            holdout_seed=3407,
            split_seed=11,
            train_seed=101,
            artifact_paths={
                "results_csv": "results.csv",
                "best_checkpoint": "weights/best.pt",
            },
            train_time_sec=123.4,
            infer_time_ms=7.8,
            peak_mem_mb=4096.0,
            param_count=20500000,
            checkpoint_size_mb=82.1,
        ),
    )
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert set(payload) >= {
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
    assert payload["status"] == "succeeded"
    assert payload["mAP50"] == 0.7
    assert payload["mAP50_95"] == 0.4
    assert payload["precision"] == 0.8
    assert payload["recall"] == 0.6
    assert payload["f1"] == pytest.approx(2 * 0.8 * 0.6 / (0.8 + 0.6), abs=1e-6)
    assert payload["artifact_paths"]["best_checkpoint"] == "weights/best.pt"
    assert payload["checkpoint_size_mb"] == 82.1


def test_write_yolo_metrics_json_marks_failed_when_results_missing(tmp_path: Path) -> None:
    from obb_baseline.runners_yolo import RunMetadata, write_yolo_metrics_json

    metrics_path = tmp_path / "metrics.json"
    write_yolo_metrics_json(
        results_csv=tmp_path / "missing.csv",
        metrics_path=metrics_path,
        run_metadata=RunMetadata(
            benchmark_name="fedo_part2_v1",
            split_manifest_hash="abc123",
            model_name="yolo11m_obb",
            preset="yolo11m-obb",
            holdout_seed=3407,
            split_seed=11,
            train_seed=101,
            artifact_paths={"work_dir": "workdirs/yolo11m_obb/split-11/seed-101"},
            train_time_sec=None,
            infer_time_ms=None,
            peak_mem_mb=None,
            param_count=None,
            checkpoint_size_mb=None,
        ),
    )
    assert metrics_path.exists()
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["benchmark_name"] == "fedo_part2_v1"
    assert payload["split_manifest_hash"] == "abc123"
    assert payload["model_name"] == "yolo11m_obb"
    assert payload["preset"] == "yolo11m-obb"
    assert payload["holdout_seed"] == 3407
    assert payload["split_seed"] == 11
    assert payload["train_seed"] == 101
    assert "artifact_paths" in payload
    assert payload["mAP50"] is None
    assert payload["mAP50_95"] is None
    assert payload["precision"] is None
    assert payload["recall"] is None
    assert payload["f1"] is None


def test_parse_yolo_outputs_reads_results_csv_and_writes_metrics(tmp_path: Path) -> None:
    from obb_baseline.runners_yolo import RunMetadata, parse_yolo_outputs

    work_dir = tmp_path / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "test_eval").mkdir(parents=True, exist_ok=True)
    (work_dir / "test_eval" / "results.csv").write_text(
        "metrics/mAP50(B),metrics/mAP50-95(B),metrics/precision(B),metrics/recall(B)\n"
        "0.7,0.4,0.8,0.6\n",
        encoding="utf-8",
    )
    metrics_path = tmp_path / "records" / "metrics.json"

    parse_yolo_outputs(
        work_dir=work_dir,
        metrics_path=metrics_path,
        run_metadata=RunMetadata(
            benchmark_name="fedo_part2_v1",
            split_manifest_hash="abc123",
            model_name="yolo11m_obb",
            preset="yolo11m-obb",
            holdout_seed=3407,
            split_seed=11,
            train_seed=101,
            artifact_paths={},
            train_time_sec=None,
            infer_time_ms=None,
            peak_mem_mb=None,
            param_count=None,
            checkpoint_size_mb=None,
        ),
        execution_status="succeeded",
    )
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert payload["status"] == "succeeded"
    assert payload["mAP50"] == 0.7
    assert payload["mAP50_95"] == 0.4
    assert payload["precision"] == 0.8
    assert payload["recall"] == 0.6
    assert payload["artifact_paths"]["test_results_csv"] == str(work_dir / "test_eval" / "results.csv")


def test_parse_yolo_outputs_prefers_test_results_csv_over_train_results_csv(tmp_path: Path) -> None:
    from obb_baseline.runners_yolo import RunMetadata, parse_yolo_outputs

    work_dir = tmp_path / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "results.csv").write_text(
        "metrics/mAP50(B),metrics/mAP50-95(B),metrics/precision(B),metrics/recall(B)\n"
        "0.1,0.05,0.2,0.1\n",
        encoding="utf-8",
    )
    (work_dir / "test_eval").mkdir(parents=True, exist_ok=True)
    (work_dir / "test_eval" / "results.csv").write_text(
        "metrics/mAP50(B),metrics/mAP50-95(B),metrics/precision(B),metrics/recall(B)\n"
        "0.7,0.4,0.8,0.6\n",
        encoding="utf-8",
    )
    metrics_path = tmp_path / "records" / "metrics.json"

    parse_yolo_outputs(
        work_dir=work_dir,
        metrics_path=metrics_path,
        run_metadata=RunMetadata(
            benchmark_name="fedo_part2_v1",
            split_manifest_hash="abc123",
            model_name="yolo11m_obb",
            preset="yolo11m-obb",
            holdout_seed=3407,
            split_seed=11,
            train_seed=101,
            artifact_paths={},
            train_time_sec=None,
            infer_time_ms=None,
            peak_mem_mb=None,
            param_count=None,
            checkpoint_size_mb=None,
        ),
        execution_status="succeeded",
    )

    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert payload["mAP50"] == 0.7
    assert payload["mAP50_95"] == 0.4
    assert payload["precision"] == 0.8
    assert payload["recall"] == 0.6


def test_parse_yolo_outputs_falls_back_to_test_metrics_in_stdout_when_test_csv_is_missing(
    tmp_path: Path,
) -> None:
    from obb_baseline.runners_yolo import RunMetadata, parse_yolo_outputs

    work_dir = tmp_path / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "test_eval").mkdir(parents=True, exist_ok=True)
    (work_dir / "results.csv").write_text(
        "metrics/mAP50(B),metrics/mAP50-95(B),metrics/precision(B),metrics/recall(B)\n"
        "0.1,0.05,0.2,0.1\n",
        encoding="utf-8",
    )
    metrics_path = tmp_path / "records" / "metrics.json"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    (metrics_path.parent / "stdout.log").write_text(
        "\n".join(
            [
                "train validation",
                "                   all        449        541      0.432       0.61      0.506      0.237",
                "Results saved to /tmp/work",
                "test evaluation",
                "split=test",
                "                   all        450        543      0.527      0.579      0.538      0.236",
                "Results saved to /tmp/work/test_eval",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    parse_yolo_outputs(
        work_dir=work_dir,
        metrics_path=metrics_path,
        run_metadata=RunMetadata(
            benchmark_name="fedo_part2_v1",
            split_manifest_hash="abc123",
            model_name="yolo11m_obb",
            preset="yolo11m-obb",
            holdout_seed=3407,
            split_seed=11,
            train_seed=101,
            artifact_paths={},
            train_time_sec=None,
            infer_time_ms=None,
            peak_mem_mb=None,
            param_count=None,
            checkpoint_size_mb=None,
        ),
        execution_status="succeeded",
    )

    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert payload["status"] == "succeeded"
    assert payload["mAP50"] == pytest.approx(0.538, abs=1e-6)
    assert payload["mAP50_95"] == pytest.approx(0.236, abs=1e-6)
    assert payload["precision"] == pytest.approx(0.527, abs=1e-6)
    assert payload["recall"] == pytest.approx(0.579, abs=1e-6)
    assert payload["artifact_paths"]["test_results_stdout"] == str(metrics_path.parent / "stdout.log")
    assert payload["artifact_paths"]["train_val_results_csv"] == str(work_dir / "results.csv")


def test_parse_yolo_outputs_marks_failed_when_execution_failed(tmp_path: Path) -> None:
    from obb_baseline.runners_yolo import RunMetadata, parse_yolo_outputs

    work_dir = tmp_path / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "results.csv").write_text(
        "metrics/mAP50(B),metrics/mAP50-95(B),metrics/precision(B),metrics/recall(B)\n"
        "0.7,0.4,0.8,0.6\n",
        encoding="utf-8",
    )
    metrics_path = tmp_path / "records" / "metrics.json"

    parse_yolo_outputs(
        work_dir=work_dir,
        metrics_path=metrics_path,
        run_metadata=RunMetadata(
            benchmark_name="fedo_part2_v1",
            split_manifest_hash="abc123",
            model_name="yolo11m_obb",
            preset="yolo11m-obb",
            holdout_seed=3407,
            split_seed=11,
            train_seed=101,
            artifact_paths={},
            train_time_sec=None,
            infer_time_ms=None,
            peak_mem_mb=None,
            param_count=None,
            checkpoint_size_mb=None,
        ),
        execution_status="failed",
    )
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["mAP50"] is None
    assert payload["mAP50_95"] is None
    assert payload["precision"] is None
    assert payload["recall"] is None
    assert payload["f1"] is None


def test_parse_yolo_outputs_marks_failed_when_results_missing_after_success(tmp_path: Path) -> None:
    from obb_baseline.runners_yolo import RunMetadata, parse_yolo_outputs

    work_dir = tmp_path / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = tmp_path / "records" / "metrics.json"

    parse_yolo_outputs(
        work_dir=work_dir,
        metrics_path=metrics_path,
        run_metadata=RunMetadata(
            benchmark_name="fedo_part2_v1",
            split_manifest_hash="abc123",
            model_name="yolo11m_obb",
            preset="yolo11m-obb",
            holdout_seed=3407,
            split_seed=11,
            train_seed=101,
            artifact_paths={},
            train_time_sec=None,
            infer_time_ms=None,
            peak_mem_mb=None,
            param_count=None,
            checkpoint_size_mb=None,
        ),
        execution_status="succeeded",
    )
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["mAP50"] is None
    assert payload["mAP50_95"] is None
    assert payload["precision"] is None
    assert payload["recall"] is None
    assert payload["f1"] is None
