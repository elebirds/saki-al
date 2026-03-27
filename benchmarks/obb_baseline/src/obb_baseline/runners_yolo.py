from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RunMetadata:
    benchmark_name: str
    split_manifest_hash: str
    model_name: str
    preset: str
    holdout_seed: int
    split_seed: int
    train_seed: int
    artifact_paths: dict[str, str]
    train_time_sec: float | None
    infer_time_ms: float | None
    peak_mem_mb: float | None
    param_count: int | None
    checkpoint_size_mb: float | None


_RAW_METRIC_KEYS = {
    "mAP50": "metrics/mAP50(B)",
    "mAP50_95": "metrics/mAP50-95(B)",
    "precision": "metrics/precision(B)",
    "recall": "metrics/recall(B)",
}

_YOLO_SUMMARY_LINE_RE = re.compile(
    r"^\s*all\s+\d+\s+\d+\s+([0-9]*\.?[0-9]+)\s+([0-9]*\.?[0-9]+)\s+([0-9]*\.?[0-9]+)\s+([0-9]*\.?[0-9]+)\s*$",
    re.MULTILINE,
)


def _parse_optional_float(value: object) -> float | None:
    if value in ("", None):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _compute_f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _empty_metrics() -> dict[str, float | None]:
    return {key: None for key in _RAW_METRIC_KEYS}


def build_yolo_train_command(
    *,
    preset: str,
    dataset_yaml: Path,
    run_dir: Path,
    work_dir: Path,
    train_seed: int,
    device: str,
    imgsz: int,
    epochs: int,
    batch_size: int,
    workers: int | None = None,
    amp: bool | None = None,
    mosaic: float | None = None,
    close_mosaic: int | None = None,
) -> list[str]:
    _ = run_dir
    command = [
        "uv",
        "run",
        "--project",
        "benchmarks/obb_baseline/envs/yolo",
        "yolo",
        "train",
        "task=obb",
        f"model={preset}",
        f"data={dataset_yaml}",
        f"project={work_dir.parent}",
        f"name={work_dir.name}",
        "exist_ok=True",
        f"seed={train_seed}",
        f"device={device}",
        f"imgsz={imgsz}",
        f"epochs={epochs}",
        f"batch={batch_size}",
    ]
    if workers is not None:
        command.append(f"workers={workers}")
    if amp is not None:
        command.append(f"amp={amp}")
    if mosaic is not None:
        command.append(f"mosaic={mosaic}")
    if close_mosaic is not None:
        command.append(f"close_mosaic={close_mosaic}")
    return command


def build_yolo_test_command(
    *,
    checkpoint_path: Path,
    dataset_yaml: Path,
    work_dir: Path,
    device: str,
    imgsz: int,
    batch_size: int,
    workers: int | None = None,
) -> list[str]:
    command = [
        "uv",
        "run",
        "--project",
        "benchmarks/obb_baseline/envs/yolo",
        "yolo",
        "val",
        "task=obb",
        f"model={checkpoint_path}",
        f"data={dataset_yaml}",
        "split=test",
        f"project={work_dir}",
        "name=test_eval",
        "exist_ok=True",
        f"device={device}",
        f"imgsz={imgsz}",
        f"batch={batch_size}",
    ]
    if workers is not None:
        command.append(f"workers={workers}")
    return command


def parse_yolo_results_csv(results_csv: Path) -> dict[str, float | None]:
    metrics = _empty_metrics()
    with results_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not any(value not in ("", None) for value in row.values()):
                continue
            metrics = {
                metric_name: _parse_optional_float(row.get(raw_key))
                for metric_name, raw_key in _RAW_METRIC_KEYS.items()
            }
    return metrics


def _parse_yolo_test_metrics_from_stdout(stdout_text: str) -> dict[str, float | None] | None:
    if not any(marker in stdout_text for marker in ("split=test", "labels/test", "/test_eval")):
        return None
    matches = list(_YOLO_SUMMARY_LINE_RE.finditer(stdout_text))
    if not matches:
        return None
    match = matches[-1]
    metrics = {
        "precision": _parse_optional_float(match.group(1)),
        "recall": _parse_optional_float(match.group(2)),
        "mAP50": _parse_optional_float(match.group(3)),
        "mAP50_95": _parse_optional_float(match.group(4)),
    }
    if all(value is None for value in metrics.values()):
        return None
    return metrics


def _build_metrics_payload(
    *,
    run_metadata: RunMetadata,
    status: str,
    metrics: dict[str, float | None],
) -> dict[str, Any]:
    payload = {
        "benchmark_name": run_metadata.benchmark_name,
        "split_manifest_hash": run_metadata.split_manifest_hash,
        "model_name": run_metadata.model_name,
        "preset": run_metadata.preset,
        "holdout_seed": run_metadata.holdout_seed,
        "split_seed": run_metadata.split_seed,
        "train_seed": run_metadata.train_seed,
        "status": status,
        "mAP50_95": metrics["mAP50_95"],
        "mAP50": metrics["mAP50"],
        "precision": metrics["precision"],
        "recall": metrics["recall"],
        "f1": _compute_f1(metrics["precision"], metrics["recall"]),
        "train_time_sec": run_metadata.train_time_sec,
        "infer_time_ms": run_metadata.infer_time_ms,
        "peak_mem_mb": run_metadata.peak_mem_mb,
        "param_count": run_metadata.param_count,
        "checkpoint_size_mb": run_metadata.checkpoint_size_mb,
        "artifact_paths": dict(run_metadata.artifact_paths),
    }
    return payload


def _resolve_yolo_results_csv(work_dir: Path) -> Path:
    test_results_csv = work_dir / "test_eval" / "results.csv"
    if test_results_csv.exists():
        return test_results_csv
    return work_dir / "results.csv"


def write_yolo_metrics_json(
    *,
    results_csv: Path,
    metrics_path: Path,
    run_metadata: RunMetadata,
) -> None:
    metrics_path.parent.mkdir(parents=True, exist_ok=True)

    status = "succeeded" if results_csv.exists() else "failed"
    metrics = parse_yolo_results_csv(results_csv) if results_csv.exists() else _empty_metrics()
    metrics_payload = _build_metrics_payload(
        run_metadata=run_metadata,
        status=status,
        metrics=metrics,
    )
    metrics_path.write_text(
        json.dumps(metrics_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_yolo_outputs(
    *,
    work_dir: Path,
    metrics_path: Path,
    run_metadata: RunMetadata,
    execution_status: str,
) -> None:
    artifact_paths = dict(run_metadata.artifact_paths)
    artifact_paths.setdefault("work_dir", str(work_dir))
    root_results_csv = work_dir / "results.csv"
    test_results_csv = work_dir / "test_eval" / "results.csv"
    stdout_log = metrics_path.parent / "stdout.log"

    status = "failed"
    metrics = _empty_metrics()
    if execution_status == "succeeded":
        if test_results_csv.exists():
            status = "succeeded"
            metrics = parse_yolo_results_csv(test_results_csv)
            artifact_paths.setdefault("results_csv", str(test_results_csv))
            artifact_paths.setdefault("test_results_csv", str(test_results_csv))
        else:
            stdout_text = ""
            if stdout_log.exists():
                stdout_text = stdout_log.read_text(encoding="utf-8")
            stdout_metrics = _parse_yolo_test_metrics_from_stdout(stdout_text)
            if stdout_metrics is not None:
                status = "succeeded"
                metrics = stdout_metrics
                artifact_paths.setdefault("test_results_stdout", str(stdout_log))
                if root_results_csv.exists():
                    artifact_paths.setdefault("train_val_results_csv", str(root_results_csv))
            elif root_results_csv.exists():
                status = "succeeded"
                metrics = parse_yolo_results_csv(root_results_csv)
                artifact_paths.setdefault("results_csv", str(root_results_csv))

    metadata = replace(run_metadata, artifact_paths=artifact_paths)
    metrics_payload = _build_metrics_payload(
        run_metadata=metadata,
        status=status,
        metrics=metrics,
    )
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(
        json.dumps(metrics_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
