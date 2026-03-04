from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any, Callable

ToFloatFn = Callable[[Any, float], float]


def _parse_metric_value(raw_value: Any, to_float: ToFloatFn) -> float | None:
    if raw_value in ("", None):
        return None
    try:
        value = float(raw_value)
    except Exception:
        value = to_float(raw_value, float("nan"))
    if not math.isfinite(value):
        return None
    return float(value)


def pick_optional_metric(row: dict[str, Any], keys: tuple[str, ...], to_float: ToFloatFn) -> float | None:
    for key in keys:
        if key in row:
            parsed = _parse_metric_value(row[key], to_float)
            if parsed is not None:
                return parsed
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
    row = {str(k): v for k, v in source.items()}
    payload: dict[str, float] = {}

    map50_keys = ("map50", "metrics/mAP50(B)", "metrics/mAP50(M)", "metrics/mAP50")
    map50_95_keys = ("map50_95", "metrics/mAP50-95(B)", "metrics/mAP50-95(M)", "metrics/mAP50-95")
    precision_keys = ("precision", "metrics/precision(B)", "metrics/precision(M)", "metrics/precision")
    recall_keys = ("recall", "metrics/recall(B)", "metrics/recall(M)", "metrics/recall")

    map50 = pick_optional_metric(row, map50_keys, to_float)
    if map50 is not None:
        payload["map50"] = float(map50)

    map50_95 = pick_optional_metric(row, map50_95_keys, to_float)
    if map50_95 is not None:
        payload["map50_95"] = float(map50_95)

    precision = pick_optional_metric(row, precision_keys, to_float)
    if precision is not None:
        payload["precision"] = float(precision)

    recall = pick_optional_metric(row, recall_keys, to_float)
    if recall is not None:
        payload["recall"] = float(recall)

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
            rows.append(normalize_metrics(item, to_float))
    return rows
