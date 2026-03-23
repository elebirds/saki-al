from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


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


_MODEL_TO_BASE_PRESET = {
    "oriented_rcnn_r50": "oriented_rcnn",
    "roi_transformer_r50": "roi_transformer",
    "r3det_r50": "r3det",
    "rtmdet_rotated_m": "rtmdet_rotated",
}

_STANDARD_METRIC_KEYS = (
    "mAP50_95",
    "mAP50",
    "precision",
    "recall",
    "f1",
)


def _parse_optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
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


def _find_metric_value(
    raw_metrics: Mapping[str, object],
    *keys: str,
) -> float | None:
    for key in keys:
        if key in raw_metrics:
            return _parse_optional_float(raw_metrics.get(key))
    return None


def render_mmrotate_config(
    *,
    model_name: str,
    data_root: Path,
    work_dir: Path,
    train_seed: int,
    score_thr: float,
    class_names: tuple[str, ...] | list[str],
) -> str:
    try:
        base_preset = _MODEL_TO_BASE_PRESET[model_name]
    except KeyError as exc:
        raise ValueError(f"unsupported mmrotate model_name: {model_name!r}") from exc

    normalized_class_names = tuple(str(name) for name in class_names)
    return (
        "# Auto-generated MMRotate config shim.\n"
        f'base_preset = "{base_preset}"\n'
        f'data_root = r"{data_root.as_posix()}"\n'
        f"class_names = {normalized_class_names!r}\n"
        f"num_classes = {len(normalized_class_names)}\n"
        f'work_dir = r"{work_dir.as_posix()}"\n'
        f"train_seed = {int(train_seed)}\n"
        f"score_thr = {float(score_thr)}\n"
    )


def build_mmrotate_train_command(
    *,
    config_path: Path,
    work_dir: Path,
    train_seed: int,
    device: str,
) -> list[str]:
    return [
        "uv",
        "run",
        "--project",
        "benchmarks/obb_baseline/envs/mmrotate",
        "python",
        "-m",
        "obb_baseline.runners_mmrotate",
        "--config",
        str(config_path),
        "--work-dir",
        str(work_dir),
        "--seed",
        str(train_seed),
        "--device",
        str(device),
    ]


def normalize_mmrotate_metrics(raw_metrics: Mapping[str, object]) -> dict[str, float | None]:
    metrics = {
        "mAP50_95": _find_metric_value(raw_metrics, "mAP50_95", "dota/mAP", "mAP", "bbox_mAP"),
        "mAP50": _find_metric_value(raw_metrics, "mAP50", "dota/AP50", "AP50", "bbox_mAP_50"),
        "precision": _find_metric_value(raw_metrics, "precision"),
        "recall": _find_metric_value(raw_metrics, "recall"),
    }
    metrics["f1"] = _compute_f1(metrics["precision"], metrics["recall"])
    return metrics


def write_mmrotate_metrics_json(
    *,
    metrics_path: Path,
    run_metadata: RunMetadata,
    status: str,
    metrics: Mapping[str, object] | None = None,
) -> None:
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_metrics = normalize_mmrotate_metrics(metrics or {})

    payload: dict[str, Any] = {
        "benchmark_name": run_metadata.benchmark_name,
        "split_manifest_hash": run_metadata.split_manifest_hash,
        "model_name": run_metadata.model_name,
        "preset": run_metadata.preset,
        "holdout_seed": run_metadata.holdout_seed,
        "split_seed": run_metadata.split_seed,
        "train_seed": run_metadata.train_seed,
        "status": status,
        "mAP50_95": normalized_metrics["mAP50_95"],
        "mAP50": normalized_metrics["mAP50"],
        "precision": normalized_metrics["precision"],
        "recall": normalized_metrics["recall"],
        "f1": normalized_metrics["f1"],
        "train_time_sec": run_metadata.train_time_sec,
        "infer_time_ms": run_metadata.infer_time_ms,
        "peak_mem_mb": run_metadata.peak_mem_mb,
        "param_count": run_metadata.param_count,
        "checkpoint_size_mb": run_metadata.checkpoint_size_mb,
        "artifact_paths": dict(run_metadata.artifact_paths),
    }
    metrics_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MMRotate runner child-process entrypoint")
    parser.add_argument("--config", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--device", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _ = args
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
