from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Callable

ToFloatFn = Callable[[Any, float], float]


def pick_metric(row: dict[str, Any], keys: tuple[str, ...], to_float: ToFloatFn) -> float:
    for key in keys:
        if key in row and row[key] not in ("", None):
            return to_float(row[key], 0.0)
    return 0.0


def pick_optional_metric(row: dict[str, Any], keys: tuple[str, ...], to_float: ToFloatFn) -> float | None:
    for key in keys:
        if key in row and row[key] not in ("", None):
            return to_float(row[key], 0.0)
    return None


def pick_loss_metric(row: dict[str, Any], to_float: ToFloatFn) -> float | None:
    box = pick_optional_metric(row, ("train/box_loss", "box_loss", "train_box_loss"), to_float)
    cls = pick_optional_metric(row, ("train/cls_loss", "cls_loss", "train_cls_loss"), to_float)
    dfl = pick_optional_metric(row, ("train/dfl_loss", "dfl_loss", "train_dfl_loss"), to_float)
    components = [value for value in (box, cls, dfl) if value is not None]
    if components:
        return float(sum(components))
    return pick_optional_metric(row, ("train/loss", "loss", "train_loss"), to_float)


def normalize_metrics(raw: dict[str, Any] | Any, to_float: ToFloatFn) -> dict[str, float]:
    source = raw if isinstance(raw, dict) else {}
    row = {str(k): to_float(v, 0.0) for k, v in source.items()}
    map50_keys = ("metrics/mAP50(B)", "metrics/mAP50(M)", "metrics/mAP50")
    map50_95_keys = ("metrics/mAP50-95(B)", "metrics/mAP50-95(M)", "metrics/mAP50-95")
    precision_keys = ("metrics/precision(B)", "metrics/precision(M)", "metrics/precision")
    recall_keys = ("metrics/recall(B)", "metrics/recall(M)", "metrics/recall")
    payload = {
        "map50": pick_metric(row, map50_keys, to_float),
        "map50_95": pick_metric(row, map50_95_keys, to_float),
        "precision": pick_metric(row, precision_keys, to_float),
        "recall": pick_metric(row, recall_keys, to_float),
    }
    loss = pick_loss_metric(row, to_float)
    if loss is not None:
        payload["loss"] = float(loss)
    return payload


def parse_results_csv(path: Path, to_float: ToFloatFn) -> list[dict[str, float]]:
    if not path.exists():
        return []
    rows: list[dict[str, float]] = []
    with path.open("r", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        for item in reader:
            map50_keys = ("metrics/mAP50(B)", "metrics/mAP50(M)", "metrics/mAP50")
            map50_95_keys = ("metrics/mAP50-95(B)", "metrics/mAP50-95(M)", "metrics/mAP50-95")
            precision_keys = ("metrics/precision(B)", "metrics/precision(M)", "metrics/precision")
            recall_keys = ("metrics/recall(B)", "metrics/recall(M)", "metrics/recall")
            rows.append(
                {
                    "map50": pick_metric(item, map50_keys, to_float),
                    "map50_95": pick_metric(item, map50_95_keys, to_float),
                    "precision": pick_metric(item, precision_keys, to_float),
                    "recall": pick_metric(item, recall_keys, to_float),
                }
            )
            loss = pick_loss_metric(item, to_float)
            if loss is not None:
                rows[-1]["loss"] = float(loss)
    return rows
