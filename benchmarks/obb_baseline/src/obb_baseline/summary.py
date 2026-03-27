from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SummaryOutputs:
    benchmark_name: str
    summary_rows: list[dict[str, object]]
    leaderboard_rows: list[dict[str, object]]


RESERVED_METRIC_KEYS = {"metrics_path"}


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isfinite(number):
            return number
        return None
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
        if math.isfinite(number):
            return number
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
            raise ValueError(f"metrics.json 含保留字段: {keys}; path={metrics_path}")

        if "model_name" in payload:
            payload_model_name = payload.pop("model_name")
            if payload_model_name != model_name:
                raise ValueError(
                    "metrics.json 字段 model_name 与 path 冲突: "
                    f"payload={payload_model_name!r}, path={model_name!r}; path={metrics_path}"
                )
        if "split_seed" in payload:
            payload_split_seed = payload.pop("split_seed")
            if _as_float(payload_split_seed) != float(split_seed):
                raise ValueError(
                    "metrics.json 字段 split_seed 与 path 冲突: "
                    f"payload={payload_split_seed!r}, path={split_seed!r}; path={metrics_path}"
                )
        if "train_seed" in payload:
            payload_train_seed = payload.pop("train_seed")
            if _as_float(payload_train_seed) != float(train_seed):
                raise ValueError(
                    "metrics.json 字段 train_seed 与 path 冲突: "
                    f"payload={payload_train_seed!r}, path={train_seed!r}; path={metrics_path}"
                )
        # f1 由汇总层统一重算，不信任 runner 回传值。
        payload.pop("f1", None)

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


def _std(values: list[float | None]) -> float | None:
    valid = [v for v in values if v is not None]
    if not valid:
        return None
    center = sum(valid) / len(valid)
    variance = sum((value - center) ** 2 for value in valid) / len(valid)
    return math.sqrt(variance)


def _format_mean_std(mean_value: object, std_value: object) -> str:
    mean_number = _as_float(mean_value)
    if mean_number is None:
        return ""
    std_number = _as_float(std_value)
    if std_number is None:
        return str(mean_number)
    return f"{mean_number} ± {std_number}"


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
            split_precision_mean = _mean([_as_float(row.get("precision")) for row in split_rows])
            split_recall_mean = _mean([_as_float(row.get("recall")) for row in split_rows])
            split_level_stats.append(
                {
                    "mAP50_95_mean": _mean([_as_float(row.get("mAP50_95")) for row in split_rows]),
                    "precision_mean": split_precision_mean,
                    "recall_mean": split_recall_mean,
                    "f1_mean": _compute_f1(split_precision_mean, split_recall_mean),
                }
            )

        m_ap50_95_mean = _mean([item["mAP50_95_mean"] for item in split_level_stats])
        precision_mean = _mean([item["precision_mean"] for item in split_level_stats])
        recall_mean = _mean([item["recall_mean"] for item in split_level_stats])
        leaderboard_rows.append(
            {
                "model_name": model_name,
                "mAP50_95_mean": m_ap50_95_mean,
                "mAP50_95_std": _std([item["mAP50_95_mean"] for item in split_level_stats]),
                "precision_mean": precision_mean,
                "precision_std": _std([item["precision_mean"] for item in split_level_stats]),
                "recall_mean": recall_mean,
                "recall_std": _std([item["recall_mean"] for item in split_level_stats]),
                "f1_mean": _mean([item["f1_mean"] for item in split_level_stats]),
                "f1_std": _std([item["f1_mean"] for item in split_level_stats]),
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
        "| model_name | mAP50_95(mean±std) | precision(mean±std) | recall(mean±std) | f1(mean±std) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in outputs.leaderboard_rows:
        lines.append(
            "| {model_name} | {mAP} | {p} | {r} | {f1} |".format(
                model_name=_sanitize_cell(row.get("model_name", "")),
                mAP=_sanitize_cell(
                    _format_mean_std(row.get("mAP50_95_mean"), row.get("mAP50_95_std"))
                ),
                p=_sanitize_cell(
                    _format_mean_std(row.get("precision_mean"), row.get("precision_std"))
                ),
                r=_sanitize_cell(
                    _format_mean_std(row.get("recall_mean"), row.get("recall_std"))
                ),
                f1=_sanitize_cell(_format_mean_std(row.get("f1_mean"), row.get("f1_std"))),
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
            "mAP50_95_std",
            "precision_mean",
            "precision_std",
            "recall_mean",
            "recall_std",
            "f1_mean",
            "f1_std",
            "split_count",
            "train_count",
        ],
    )
    (benchmark_root / "summary.md").write_text(
        render_summary_markdown(outputs),
        encoding="utf-8",
    )
