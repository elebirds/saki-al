from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SummaryOutputs:
    benchmark_name: str
    summary_rows: list[dict[str, object]]
    leaderboard_rows: list[dict[str, object]]


RESERVED_METRIC_KEYS = {"model_name", "split_seed", "train_seed", "metrics_path", "f1"}


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _compute_f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _parse_metrics_identity(metrics_path: Path, records_root: Path) -> tuple[str, int, int]:
    rel = metrics_path.relative_to(records_root)
    parts = rel.parts
    if len(parts) != 4:
        raise ValueError(f"metrics.json 路径不符合约定: {metrics_path}")
    model_name, split_dir, seed_dir, file_name = parts
    if file_name != "metrics.json":
        raise ValueError(f"metrics.json 路径不符合约定: {metrics_path}")
    if not split_dir.startswith("split-") or not seed_dir.startswith("seed-"):
        raise ValueError(f"metrics.json 路径不符合约定: {metrics_path}")
    try:
        split_seed = int(split_dir.split("-", 1)[1])
        train_seed = int(seed_dir.split("-", 1)[1])
    except ValueError as exc:
        raise ValueError(f"metrics.json 路径不符合约定: {metrics_path}") from exc
    return model_name, split_seed, train_seed


def _sanitize_cell(value: object) -> object:
    if value is None:
        return ""
    return value


def load_metrics_rows(records_root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for metrics_path in sorted(records_root.rglob("metrics.json")):
        model_name, split_seed, train_seed = _parse_metrics_identity(metrics_path, records_root)

        with metrics_path.open("r", encoding="utf-8") as handle:
            payload: dict[str, Any] = json.load(handle)
        duplicate_reserved = RESERVED_METRIC_KEYS.intersection(payload)
        if duplicate_reserved:
            keys = ", ".join(sorted(duplicate_reserved))
            raise ValueError(f"metrics.json 含保留字段: {keys}")
        row: dict[str, object] = {
            "model_name": model_name,
            "split_seed": split_seed,
            "train_seed": train_seed,
            "metrics_path": str(metrics_path),
        }
        row.update(payload)
        precision = _as_float(row.get("precision"))
        recall = _as_float(row.get("recall"))
        m_ap50_95 = _as_float(row.get("mAP50_95"))
        row["precision"] = precision
        row["recall"] = recall
        row["mAP50_95"] = m_ap50_95
        row["f1"] = _compute_f1(precision, recall)
        rows.append(row)
    return rows


def _mean(values: list[float | None]) -> float | None:
    valid = [v for v in values if v is not None]
    if not valid:
        return None
    return sum(valid) / len(valid)


def collect_suite_outputs(*, benchmark_name: str, benchmark_root: Path) -> SummaryOutputs:
    records_root = benchmark_root / "records"
    summary_rows = load_metrics_rows(records_root)
    summary_rows.sort(
        key=lambda row: (
            str(row.get("model_name", "")),
            int(row.get("split_seed", -1)),
            int(row.get("train_seed", -1)),
        )
    )

    grouped: dict[str, dict[int, list[dict[str, object]]]] = {}
    for row in summary_rows:
        model_name = str(row.get("model_name", ""))
        split_seed = int(row.get("split_seed", -1))
        grouped.setdefault(model_name, {}).setdefault(split_seed, []).append(row)

    leaderboard_rows: list[dict[str, object]] = []
    for model_name, split_groups in grouped.items():
        split_level_stats: list[dict[str, float | None]] = []
        for split_seed in sorted(split_groups):
            split_rows = split_groups[split_seed]
            split_level_stats.append(
                {
                    "mAP50_95_mean": _mean([_as_float(row.get("mAP50_95")) for row in split_rows]),
                    "precision_mean": _mean([_as_float(row.get("precision")) for row in split_rows]),
                    "recall_mean": _mean([_as_float(row.get("recall")) for row in split_rows]),
                }
            )

        m_ap50_95_mean = _mean([item["mAP50_95_mean"] for item in split_level_stats])
        precision_mean = _mean([item["precision_mean"] for item in split_level_stats])
        recall_mean = _mean([item["recall_mean"] for item in split_level_stats])
        leaderboard_rows.append(
            {
                "model_name": model_name,
                "mAP50_95_mean": m_ap50_95_mean,
                "precision_mean": precision_mean,
                "recall_mean": recall_mean,
                "f1_mean": _compute_f1(precision_mean, recall_mean),
                "split_count": len(split_level_stats),
                "train_count": sum(len(v) for v in split_groups.values()),
            }
        )

    leaderboard_rows.sort(
        key=lambda row: (
            -1.0
            * (
                row["mAP50_95_mean"]
                if isinstance(row.get("mAP50_95_mean"), (float, int))
                else float("-inf")
            )
        )
    )
    return SummaryOutputs(
        benchmark_name=benchmark_name,
        summary_rows=summary_rows,
        leaderboard_rows=leaderboard_rows,
    )


def render_summary_markdown(outputs: SummaryOutputs) -> str:
    top_model = (
        str(outputs.leaderboard_rows[0]["model_name"]) if outputs.leaderboard_rows else "-"
    )
    lines = [
        f"# {outputs.benchmark_name} 汇总",
        "",
        f"精度最佳模型（按 mAP50_95）：`{top_model}`",
        "",
        "## Leaderboard",
        "",
        "| model_name | mAP50_95_mean | precision_mean | recall_mean | f1_mean |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in outputs.leaderboard_rows:
        lines.append(
            "| {model_name} | {mAP} | {p} | {r} | {f1} |".format(
                model_name=_sanitize_cell(row.get("model_name", "")),
                mAP=_sanitize_cell(row.get("mAP50_95_mean", "")),
                p=_sanitize_cell(row.get("precision_mean", "")),
                r=_sanitize_cell(row.get("recall_mean", "")),
                f1=_sanitize_cell(row.get("f1_mean", "")),
            )
        )
    return "\n".join(lines) + "\n"


def _ordered_fieldnames(rows: list[dict[str, object]], core_fields: list[str]) -> list[str]:
    extras: set[str] = set()
    for row in rows:
        for key in row:
            if key not in core_fields:
                extras.add(key)
    return [*core_fields, *sorted(extras)]


def _write_csv(rows: list[dict[str, object]], target: Path, *, core_fields: list[str]) -> None:
    if not rows:
        target.write_text("", encoding="utf-8")
        return
    fieldnames = _ordered_fieldnames(rows, core_fields)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _sanitize_cell(row.get(key)) for key in fieldnames})


def write_suite_outputs(outputs: SummaryOutputs, benchmark_root: Path) -> None:
    _write_csv(
        outputs.summary_rows,
        benchmark_root / "summary.csv",
        core_fields=[
            "model_name",
            "split_seed",
            "train_seed",
            "metrics_path",
            "mAP50_95",
            "precision",
            "recall",
            "f1",
        ],
    )
    _write_csv(
        outputs.leaderboard_rows,
        benchmark_root / "leaderboard.csv",
        core_fields=[
            "model_name",
            "mAP50_95_mean",
            "precision_mean",
            "recall_mean",
            "f1_mean",
            "split_count",
            "train_count",
        ],
    )
    (benchmark_root / "summary.md").write_text(
        render_summary_markdown(outputs),
        encoding="utf-8",
    )
