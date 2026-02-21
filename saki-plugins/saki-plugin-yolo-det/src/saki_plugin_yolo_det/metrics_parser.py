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


def normalize_metrics(raw: dict[str, Any] | Any, to_float: ToFloatFn) -> dict[str, float]:
    source = raw if isinstance(raw, dict) else {}
    row = {str(k): to_float(v, 0.0) for k, v in source.items()}
    map50_keys = ("metrics/mAP50(B)", "metrics/mAP50(M)", "metrics/mAP50")
    map50_95_keys = ("metrics/mAP50-95(B)", "metrics/mAP50-95(M)", "metrics/mAP50-95")
    precision_keys = ("metrics/precision(B)", "metrics/precision(M)", "metrics/precision")
    recall_keys = ("metrics/recall(B)", "metrics/recall(M)", "metrics/recall")
    return {
        "map50": pick_metric(row, map50_keys, to_float),
        "map50_95": pick_metric(row, map50_95_keys, to_float),
        "precision": pick_metric(row, precision_keys, to_float),
        "recall": pick_metric(row, recall_keys, to_float),
    }


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
    return rows
