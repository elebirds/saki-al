from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass
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
) -> list[str]:
    _ = run_dir
    return [
        "uv",
        "run",
        "--project",
        "benchmarks/obb_baseline/envs/yolo",
        "python",
        "-m",
        "ultralytics",
        "train",
        "task=obb",
        f"model={preset}",
        f"data={dataset_yaml}",
        f"project={work_dir.parent}",
        f"name={work_dir.name}",
        f"seed={train_seed}",
        f"device={device}",
        f"imgsz={imgsz}",
        f"epochs={epochs}",
        f"batch={batch_size}",
    ]


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


def write_yolo_metrics_json(
    *,
    results_csv: Path,
    metrics_path: Path,
    status_path: Path,
    run_metadata: RunMetadata,
) -> None:
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.parent.mkdir(parents=True, exist_ok=True)

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

    status_payload = {
        "status": status,
        "results_csv": str(results_csv),
        "run_metadata": asdict(run_metadata),
    }
    status_path.write_text(
        json.dumps(status_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
