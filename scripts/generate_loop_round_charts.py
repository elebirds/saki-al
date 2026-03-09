#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import io
import json
import math
import os
import re
import shutil
import statistics
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RoundRow:
    base_name: str
    seed: str
    loop_name: str
    loop_id: str
    global_seed: str
    round_index: int
    attempt_index: int
    state: str
    metrics_source: str
    map50: float | None
    map50_95: float | None
    precision: float | None
    recall: float | None
    loss: float | None
    train_map50: float | None
    train_map50_95: float | None
    eval_map50: float | None
    eval_map50_95: float | None
    confirmed_selected_count: int
    confirmed_revealed_count: int
    confirmed_effective_min_required: int
    started_at_sh: str
    ended_at_sh: str
    terminal_reason: str


@dataclass(frozen=True)
class AggregateRow:
    base_name: str
    round_index: int
    seed_count: int
    completed_count: int
    running_count: int
    pending_count: int
    map50_mean: float | None
    map50_std: float | None
    map50_95_mean: float | None
    map50_95_std: float | None
    precision_mean: float | None
    recall_mean: float | None
    loss_mean: float | None


GROUP_COLORS = {
    "sim-aug-rect-yolov8l": "#0d8a72",
    "sim-uncertainty-yolov8l": "#df5f2d",
    "sim-aug-boundary-yolov8l": "#1f4db6",
    "sim-random-yolov8l": "#7b3fe4",
    "sim-aug-obb-yolov8l": "#b11c47",
}

SEED_COLORS = {
    "1": "#0c7c59",
    "2": "#d95d39",
    "3": "#4f46e5",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate loop round charts from Saki runtime DB.")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--database", default="saki")
    parser.add_argument("--password-env", default="PGPASSWORD")
    parser.add_argument("--out-dir", default="runs/reports")
    return parser.parse_args()


def require_psql() -> str:
    psql = shutil.which("psql")
    if not psql:
        raise SystemExit("psql 未找到，无法执行数据库只读查询。")
    return psql


def run_copy(*, psql: str, env: dict[str, str], host: str, port: int, user: str, database: str, query: str) -> list[dict[str, str]]:
    cmd = [
        psql,
        "-h",
        host,
        "-p",
        str(port),
        "-U",
        user,
        "-d",
        database,
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-P",
        "pager=off",
        "-c",
        f"COPY ({query}) TO STDOUT WITH CSV HEADER",
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
    return list(csv.DictReader(io.StringIO(result.stdout)))


def parse_json_map(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def metric_value(metrics: dict[str, Any], key: str) -> float | None:
    value = metrics.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def step_sort_key(step: dict[str, Any]) -> tuple[int, str]:
    return int(step["step_index"] or 0), str(step["step_created_at_sh"] or "")


def pick_non_empty_step_metrics(step: dict[str, Any]) -> dict[str, Any] | None:
    metrics = step.get("metrics") or {}
    return dict(metrics) if metrics else None


def pick_latest_step_type_metrics(ordered_steps: list[dict[str, Any]], step_type: str) -> dict[str, Any]:
    for require_succeeded in (True, False):
        for step in reversed(ordered_steps):
            if str(step.get("step_type") or "").strip().lower() != step_type:
                continue
            status_text = str(step.get("task_status") or step.get("step_state") or "").strip().lower()
            if require_succeeded and status_text != "succeeded":
                continue
            metrics = pick_non_empty_step_metrics(step)
            if metrics is not None:
                return metrics
    return {}


def pick_final_metrics_with_source(ordered_steps: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    for stage in ("eval", "train"):
        for step in reversed(ordered_steps):
            if str(step.get("step_type") or "").strip().lower() != stage:
                continue
            metrics = pick_non_empty_step_metrics(step)
            if metrics is not None:
                return metrics, stage
    for step in reversed(ordered_steps):
        metrics = pick_non_empty_step_metrics(step)
        if metrics is not None:
            return metrics, "other"
    return {}, "none"


def identify_group(name: str, valid_seed_prefixes: set[str]) -> tuple[str, str]:
    matched = re.match(r"^(.*)-(\d+)$", name)
    if matched and matched.group(1) in valid_seed_prefixes and matched.group(2) in {"1", "2", "3"}:
        return matched.group(1), matched.group(2)
    return name, ""


def mean_std(values: list[float | None]) -> tuple[float | None, float | None]:
    cleaned = [value for value in values if value is not None]
    if not cleaned:
        return None, None
    mean = sum(cleaned) / len(cleaned)
    std = statistics.stdev(cleaned) if len(cleaned) >= 2 else 0.0
    return mean, std


def format_metric(value: float | None, digits: int = 4) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def build_round_rows(
    *,
    loops: list[dict[str, str]],
    rounds: list[dict[str, str]],
    steps: list[dict[str, str]],
) -> tuple[list[RoundRow], list[AggregateRow], list[dict[str, Any]]]:
    loop_by_id = {row["loop_id"]: row for row in loops}

    names = [row["name"] for row in loops]
    seed_suffix_groups: dict[str, dict[str, str]] = defaultdict(dict)
    for name in names:
        matched = re.match(r"^(.*)-(\d+)$", name)
        if not matched:
            continue
        prefix, suffix = matched.group(1), matched.group(2)
        if suffix in {"1", "2", "3"}:
            seed_suffix_groups[prefix][suffix] = name
    valid_seed_prefixes = {prefix for prefix, mapping in seed_suffix_groups.items() if len(mapping) >= 2}

    steps_by_round: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in steps:
        typed = dict(row)
        typed["metrics"] = parse_json_map(row["result_metrics_json"])
        steps_by_round[row["round_id"]].append(typed)

    round_rows: list[RoundRow] = []
    raw_rows: list[dict[str, Any]] = []
    for row in rounds:
        if row["state"] == "FAILED":
            continue
        loop = loop_by_id[row["loop_id"]]
        base_name, seed = identify_group(loop["name"], valid_seed_prefixes)
        ordered_steps = sorted(steps_by_round.get(row["round_id"], []), key=step_sort_key)
        train_metrics = pick_latest_step_type_metrics(ordered_steps, "train")
        eval_metrics = pick_latest_step_type_metrics(ordered_steps, "eval")
        final_metrics, source = pick_final_metrics_with_source(ordered_steps)
        round_final = parse_json_map(row["round_final_metrics_json"])
        if not final_metrics and round_final:
            final_metrics, source = round_final, "round"

        round_row = RoundRow(
            base_name=base_name,
            seed=seed,
            loop_name=loop["name"],
            loop_id=row["loop_id"],
            global_seed=loop["global_seed"],
            round_index=int(row["round_index"]),
            attempt_index=int(row["attempt_index"]),
            state=row["state"],
            metrics_source=source,
            map50=metric_value(final_metrics, "map50"),
            map50_95=metric_value(final_metrics, "map50_95"),
            precision=metric_value(final_metrics, "precision"),
            recall=metric_value(final_metrics, "recall"),
            loss=metric_value(final_metrics, "loss"),
            train_map50=metric_value(train_metrics, "map50"),
            train_map50_95=metric_value(train_metrics, "map50_95"),
            eval_map50=metric_value(eval_metrics, "map50"),
            eval_map50_95=metric_value(eval_metrics, "map50_95"),
            confirmed_selected_count=int(row["confirmed_selected_count"]),
            confirmed_revealed_count=int(row["confirmed_revealed_count"]),
            confirmed_effective_min_required=int(row["confirmed_effective_min_required"]),
            started_at_sh=row["started_at_sh"],
            ended_at_sh=row["ended_at_sh"],
            terminal_reason=row["terminal_reason"],
        )
        round_rows.append(round_row)
        raw_rows.append(round_row.__dict__)

    round_rows.sort(key=lambda item: (item.base_name, int(item.seed) if item.seed else 999, item.loop_name, item.round_index, item.attempt_index))

    grouped: dict[tuple[str, int], list[RoundRow]] = defaultdict(list)
    for row in round_rows:
        if not row.seed:
            continue
        grouped[(row.base_name, row.round_index)].append(row)

    aggregate_rows: list[AggregateRow] = []
    for (base_name, round_index), items in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1])):
        map50_mean, map50_std = mean_std([item.map50 for item in items])
        map50_95_mean, map50_95_std = mean_std([item.map50_95 for item in items])
        precision_mean, _ = mean_std([item.precision for item in items])
        recall_mean, _ = mean_std([item.recall for item in items])
        loss_mean, _ = mean_std([item.loss for item in items])
        aggregate_rows.append(
            AggregateRow(
                base_name=base_name,
                round_index=round_index,
                seed_count=len(items),
                completed_count=sum(1 for item in items if item.state == "COMPLETED"),
                running_count=sum(1 for item in items if item.state == "RUNNING"),
                pending_count=sum(1 for item in items if item.state == "PENDING"),
                map50_mean=map50_mean,
                map50_std=map50_std,
                map50_95_mean=map50_95_mean,
                map50_95_std=map50_95_std,
                precision_mean=precision_mean,
                recall_mean=recall_mean,
                loss_mean=loss_mean,
            )
        )

    return round_rows, aggregate_rows, raw_rows


def write_tsv(path: Path, rows: list[RoundRow]) -> None:
    fieldnames = [
        "base_name",
        "seed",
        "loop_name",
        "loop_id",
        "global_seed",
        "round_index",
        "attempt_index",
        "state",
        "metrics_source",
        "map50",
        "map50_95",
        "precision",
        "recall",
        "loss",
        "train_map50",
        "train_map50_95",
        "eval_map50",
        "eval_map50_95",
        "confirmed_selected_count",
        "confirmed_revealed_count",
        "confirmed_effective_min_required",
        "started_at_sh",
        "ended_at_sh",
        "terminal_reason",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in rows:
            payload = row.__dict__.copy()
            for key in ("map50", "map50_95", "precision", "recall", "loss", "train_map50", "train_map50_95", "eval_map50", "eval_map50_95"):
                value = payload[key]
                payload[key] = "" if value is None else f"{value:.6f}"
            writer.writerow(payload)


def scale_linear(value: float, domain_min: float, domain_max: float, range_min: float, range_max: float) -> float:
    if math.isclose(domain_min, domain_max):
        return (range_min + range_max) / 2
    ratio = (value - domain_min) / (domain_max - domain_min)
    return range_min + ratio * (range_max - range_min)


def svg_text(x: float, y: float, text: str, *, size: int = 14, fill: str = "#0e2431", anchor: str = "start", weight: int = 500, opacity: float = 1.0) -> str:
    escaped = html.escape(text)
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" font-size="{size}" '
        f'font-family="Avenir Next, Segoe UI, sans-serif" font-weight="{weight}" '
        f'text-anchor="{anchor}" opacity="{opacity:.2f}">{escaped}</text>'
    )


def build_group_mean_svg(path: Path, aggregates: list[AggregateRow]) -> None:
    groups = [name for name in GROUP_COLORS if any(row.base_name == name for row in aggregates)]
    width = 1200
    height = 760
    margin_left = 96
    margin_right = 36
    margin_top = 96
    margin_bottom = 72
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    max_round = max((row.round_index for row in aggregates), default=1)
    max_metric = max((row.map50_95_mean or 0.0 for row in aggregates), default=0.5)
    upper_metric = max(0.45, math.ceil(max_metric * 20) / 20)

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none">',
        '<defs>',
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">',
        '<stop offset="0%" stop-color="#fbf7ef"/>',
        '<stop offset="100%" stop-color="#f1ece2"/>',
        "</linearGradient>",
        '<filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">',
        '<feDropShadow dx="0" dy="12" stdDeviation="16" flood-color="#7d63450f"/>',
        "</filter>",
        "</defs>",
        f'<rect width="{width}" height="{height}" rx="28" fill="url(#bg)"/>',
        f'<rect x="18" y="18" width="{width - 36}" height="{height - 36}" rx="20" fill="#fffdfa" stroke="#d8cfbf" stroke-width="1"/>',
        svg_text(48, 56, "Project 980ff7aa Round Trend", size=28, weight=700),
        svg_text(48, 84, "三 seed 实验按 round 的 mAP50_95 均值轨迹", size=14, fill="#6d6254", weight=500),
    ]

    for i in range(6):
        value = upper_metric * i / 5
        y = scale_linear(value, 0, upper_metric, margin_top + plot_height, margin_top)
        lines.append(f'<line x1="{margin_left}" y1="{y:.1f}" x2="{width - margin_right}" y2="{y:.1f}" stroke="#e1d9cd" stroke-width="1"/>')
        lines.append(svg_text(margin_left - 14, y + 5, f"{value:.2f}", size=12, fill="#73685b", anchor="end", weight=500))

    for round_index in range(1, max_round + 1):
        x = scale_linear(round_index, 1, max_round, margin_left, margin_left + plot_width)
        lines.append(f'<line x1="{x:.1f}" y1="{margin_top}" x2="{x:.1f}" y2="{margin_top + plot_height}" stroke="#efe8de" stroke-width="1"/>')
        lines.append(svg_text(x, margin_top + plot_height + 28, str(round_index), size=12, fill="#73685b", anchor="middle"))

    for group in groups:
        group_rows = [row for row in aggregates if row.base_name == group and row.map50_95_mean is not None]
        if not group_rows:
            continue
        points = []
        for row in group_rows:
            x = scale_linear(row.round_index, 1, max_round, margin_left, margin_left + plot_width)
            y = scale_linear(row.map50_95_mean or 0.0, 0, upper_metric, margin_top + plot_height, margin_top)
            points.append((x, y, row))
        path_d = " ".join(
            f'{"M" if idx == 0 else "L"} {x:.1f} {y:.1f}'
            for idx, (x, y, _) in enumerate(points)
        )
        color = GROUP_COLORS[group]
        lines.append(f'<path d="{path_d}" stroke="{color}" stroke-width="4" fill="none" stroke-linecap="round" stroke-linejoin="round" filter="url(#shadow)"/>')
        for x, y, row in points:
            lines.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.5" fill="{color}" stroke="#fffdfa" stroke-width="2"/>')
            label = f"r{row.round_index} {format_metric(row.map50_95_mean)}"
            lines.append(f'<title>{html.escape(group)} {html.escape(label)}</title>')

    legend_x = width - 320
    legend_y = 56
    for idx, group in enumerate(groups):
        y = legend_y + idx * 28
        color = GROUP_COLORS[group]
        lines.append(f'<line x1="{legend_x}" y1="{y}" x2="{legend_x + 26}" y2="{y}" stroke="{color}" stroke-width="4" stroke-linecap="round"/>')
        lines.append(svg_text(legend_x + 36, y + 5, group, size=13, fill="#4b4035"))

    lines.append(svg_text(margin_left, height - 18, "失败 round 已剔除；空点表示该 round 尚无可用 metrics。", size=12, fill="#7d7265"))
    lines.append("</svg>")
    path.write_text("\n".join(lines), encoding="utf-8")


def build_seed_small_multiples_svg(path: Path, round_rows: list[RoundRow]) -> None:
    groups = [name for name in GROUP_COLORS if any(row.base_name == name and row.seed for row in round_rows)]
    width = 1280
    height = 900
    panel_cols = 2
    panel_width = 560
    panel_height = 220
    panel_gap_x = 60
    panel_gap_y = 36
    start_x = 44
    start_y = 108

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none">',
        '<defs>',
        '<linearGradient id="board" x1="0" y1="0" x2="1" y2="1">',
        '<stop offset="0%" stop-color="#0f1724"/>',
        '<stop offset="100%" stop-color="#1e293b"/>',
        "</linearGradient>",
        "</defs>",
        f'<rect width="{width}" height="{height}" rx="30" fill="url(#board)"/>',
        svg_text(46, 58, "Seed Paths", size=30, fill="#f8f1e7", weight=700),
        svg_text(46, 86, "每个实验组三条 seed 轨迹，指标为 mAP50_95", size=14, fill="#d3c8ba"),
    ]

    for index, group in enumerate(groups):
        row = index // panel_cols
        col = index % panel_cols
        panel_x = start_x + col * (panel_width + panel_gap_x)
        panel_y = start_y + row * (panel_height + panel_gap_y)
        lines.append(f'<rect x="{panel_x}" y="{panel_y}" width="{panel_width}" height="{panel_height}" rx="18" fill="#f8f1e7" opacity="0.96"/>')
        lines.append(svg_text(panel_x + 18, panel_y + 28, group, size=15, fill="#0f1724", weight=700))

        group_rows = [item for item in round_rows if item.base_name == group and item.seed]
        max_round = max((item.round_index for item in group_rows), default=1)
        metric_max = max((item.map50_95 or 0.0 for item in group_rows), default=0.5)
        upper_metric = max(0.45, math.ceil(metric_max * 20) / 20)
        inner_left = panel_x + 50
        inner_right = panel_x + panel_width - 18
        inner_top = panel_y + 36
        inner_bottom = panel_y + panel_height - 34

        for i in range(5):
            value = upper_metric * i / 4
            y = scale_linear(value, 0, upper_metric, inner_bottom, inner_top)
            lines.append(f'<line x1="{inner_left}" y1="{y:.1f}" x2="{inner_right}" y2="{y:.1f}" stroke="#d9cfbe" stroke-width="1"/>')
        for round_index in range(1, max_round + 1):
            x = scale_linear(round_index, 1, max_round, inner_left, inner_right)
            lines.append(f'<line x1="{x:.1f}" y1="{inner_top}" x2="{x:.1f}" y2="{inner_bottom}" stroke="#ede5d9" stroke-width="1"/>')

        for seed in ("1", "2", "3"):
            seed_rows = sorted(
                [item for item in group_rows if item.seed == seed and item.map50_95 is not None],
                key=lambda item: (item.round_index, item.attempt_index),
            )
            if not seed_rows:
                continue
            points = []
            for item in seed_rows:
                x = scale_linear(item.round_index, 1, max_round, inner_left, inner_right)
                y = scale_linear(item.map50_95 or 0.0, 0, upper_metric, inner_bottom, inner_top)
                points.append((x, y))
            path_d = " ".join(
                f'{"M" if point_index == 0 else "L"} {x:.1f} {y:.1f}'
                for point_index, (x, y) in enumerate(points)
            )
            color = SEED_COLORS[seed]
            lines.append(f'<path d="{path_d}" stroke="{color}" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>')
            last_x, last_y = points[-1]
            lines.append(f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="4.2" fill="{color}" stroke="#f8f1e7" stroke-width="1.5"/>')
            lines.append(svg_text(last_x + 8, last_y + 4, f"s{seed}", size=11, fill=color, weight=700))

        lines.append(svg_text(inner_left, inner_bottom + 22, "round", size=11, fill="#706252"))
        lines.append(svg_text(inner_left - 8, inner_top + 2, "mAP50_95", size=11, fill="#706252", anchor="end"))

    lines.append(svg_text(46, height - 18, "seed 1/2/3 对应 global_seed 42 / 6 / 114514", size=12, fill="#d3c8ba"))
    lines.append("</svg>")
    path.write_text("\n".join(lines), encoding="utf-8")


def build_status_svg(path: Path, aggregates: list[AggregateRow]) -> None:
    groups = [name for name in GROUP_COLORS if any(row.base_name == name for row in aggregates)]
    latest_by_group: dict[str, AggregateRow] = {}
    for row in aggregates:
        previous = latest_by_group.get(row.base_name)
        if previous is None or row.round_index > previous.round_index:
            latest_by_group[row.base_name] = row

    width = 900
    height = 460
    margin_left = 220
    bar_height = 34
    gap = 24
    top = 90
    chart_width = width - margin_left - 60
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none">',
        '<rect width="100%" height="100%" rx="26" fill="#fcfaf6"/>',
        svg_text(34, 52, "Latest Round Status", size=28, weight=700),
        svg_text(34, 80, "每个实验组当前最新 round 的 seed 覆盖状态", size=14, fill="#6d6254"),
    ]
    for idx, group in enumerate(groups):
        row = latest_by_group[group]
        y = top + idx * (bar_height + gap)
        lines.append(svg_text(34, y + 23, f"{group} · r{row.round_index}", size=13, fill="#352d26", weight=700))
        x = margin_left
        total = max(row.seed_count, 1)
        segments = [
            (row.completed_count, "#0f8a72"),
            (row.running_count, "#e07a2e"),
            (row.pending_count, "#a8b4c3"),
        ]
        for value, color in segments:
            segment_width = chart_width * value / total
            if segment_width <= 0:
                continue
            lines.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{segment_width:.1f}" height="{bar_height}" rx="10" fill="{color}"/>')
            x += segment_width
        lines.append(f'<rect x="{margin_left}" y="{y}" width="{chart_width}" height="{bar_height}" rx="10" fill="none" stroke="#d4ccbe"/>')
        label = f"C{row.completed_count} / R{row.running_count} / P{row.pending_count}"
        lines.append(svg_text(margin_left + chart_width + 16, y + 23, label, size=12, fill="#5f5448"))
    lines.append(svg_text(34, height - 20, "色块分别表示 completed / running / pending 的 seed 数。", size=12, fill="#7a6f62"))
    lines.append("</svg>")
    path.write_text("\n".join(lines), encoding="utf-8")


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def build_dashboard_html(
    path: Path,
    *,
    project_id: str,
    generated_at: str,
    round_rows: list[RoundRow],
    aggregates: list[AggregateRow],
) -> None:
    group_cards: list[dict[str, Any]] = []
    grouped_rounds: dict[str, list[RoundRow]] = defaultdict(list)
    for row in round_rows:
        if row.seed:
            grouped_rounds[row.base_name].append(row)

    for group_name in GROUP_COLORS:
        if group_name not in grouped_rounds:
            continue
        items = grouped_rounds[group_name]
        latest_round = max(items, key=lambda item: (item.round_index, item.attempt_index))
        latest_metric_round = max(
            (item for item in items if item.map50_95 is not None),
            key=lambda item: (item.round_index, item.attempt_index),
            default=None,
        )
        group_cards.append(
            {
                "name": group_name,
                "color": GROUP_COLORS[group_name],
                "latestRound": latest_round.round_index,
                "latestState": latest_round.state,
                "latestMetricRound": latest_metric_round.round_index if latest_metric_round else None,
                "latestMap5095": latest_metric_round.map50_95 if latest_metric_round else None,
                "seedCoverage": sorted({item.seed for item in items}),
            }
        )

    summary = {
        "projectId": project_id,
        "generatedAt": generated_at,
        "roundCount": len(round_rows),
        "groupCount": len(group_cards),
        "runningRounds": sum(1 for row in round_rows if row.state == "RUNNING"),
        "pendingRounds": sum(1 for row in round_rows if row.state == "PENDING"),
        "completedRounds": sum(1 for row in round_rows if row.state == "COMPLETED"),
    }

    dashboard_rows = [row.__dict__ for row in round_rows]
    dashboard_aggregates = [row.__dict__ for row in aggregates]

    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Loop Round Dashboard · {html.escape(project_id)}</title>
  <style>
    :root {{
      --paper: #f7f2e8;
      --paper-2: #fffdf8;
      --ink: #122033;
      --muted: #6c6357;
      --line: rgba(18, 32, 51, 0.14);
      --accent: #c7541f;
      --teal: #0d8a72;
      --blue: #2048a8;
      --shadow: 0 18px 60px rgba(34, 24, 8, 0.10);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at 20% 10%, rgba(199, 84, 31, 0.16), transparent 28%),
        radial-gradient(circle at 80% 0%, rgba(13, 138, 114, 0.16), transparent 26%),
        linear-gradient(180deg, #efe8dc 0%, #f9f5ee 42%, #f6f1e8 100%);
      min-height: 100vh;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image: linear-gradient(rgba(18, 32, 51, 0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(18, 32, 51, 0.035) 1px, transparent 1px);
      background-size: 24px 24px;
      mask-image: radial-gradient(circle at center, black 60%, transparent 100%);
    }}
    .page {{
      max-width: 1380px;
      margin: 0 auto;
      padding: 36px 22px 60px;
    }}
    .hero {{
      display: grid;
      grid-template-columns: 1.35fr 0.65fr;
      gap: 22px;
      align-items: stretch;
    }}
    .headline, .summary-card, .panel {{
      background: rgba(255, 253, 248, 0.82);
      backdrop-filter: blur(10px);
      border: 1px solid rgba(18, 32, 51, 0.10);
      box-shadow: var(--shadow);
      border-radius: 28px;
      overflow: hidden;
      position: relative;
    }}
    .headline {{
      padding: 28px 30px 30px;
      min-height: 250px;
    }}
    .headline::after {{
      content: "ROUND ATLAS";
      position: absolute;
      right: -10px;
      top: 14px;
      font-size: 72px;
      font-weight: 700;
      letter-spacing: 0.18em;
      color: rgba(18, 32, 51, 0.05);
      transform: rotate(-6deg);
    }}
    .eyebrow {{
      display: inline-flex;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(18, 32, 51, 0.06);
      font-size: 12px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 20px 0 14px;
      font-size: clamp(34px, 5vw, 64px);
      line-height: 0.98;
      font-family: "Iowan Old Style", "Palatino Linotype", serif;
      font-weight: 700;
      max-width: 10ch;
    }}
    .lede {{
      margin: 0;
      max-width: 66ch;
      color: var(--muted);
      line-height: 1.7;
      font-size: 15px;
    }}
    .hero-metrics {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-top: 24px;
      max-width: 560px;
    }}
    .metric-chip {{
      padding: 14px 16px;
      border-radius: 18px;
      background: linear-gradient(145deg, rgba(255,255,255,0.9), rgba(245,239,230,0.9));
      border: 1px solid rgba(18, 32, 51, 0.09);
    }}
    .metric-chip strong {{
      display: block;
      font-size: 26px;
      margin-bottom: 4px;
      font-weight: 700;
    }}
    .metric-chip span {{
      font-size: 12px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.12em;
    }}
    .summary-card {{
      padding: 28px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      background:
        linear-gradient(160deg, rgba(18,32,51,0.95), rgba(18,32,51,0.84)),
        radial-gradient(circle at top right, rgba(199,84,31,0.3), transparent 35%);
      color: #f9f5ef;
    }}
    .summary-card h2 {{
      margin: 0 0 10px;
      font-size: 18px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }}
    .summary-card p {{
      margin: 0;
      color: rgba(249, 245, 239, 0.76);
      line-height: 1.7;
      font-size: 14px;
    }}
    .score-strip {{
      display: grid;
      gap: 12px;
      margin-top: 28px;
    }}
    .score-strip div {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 14px;
      padding-bottom: 10px;
      border-bottom: 1px solid rgba(249, 245, 239, 0.12);
    }}
    .score-strip b {{
      font-size: 26px;
      font-weight: 700;
      letter-spacing: -0.03em;
    }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(340px, 0.8fr);
      gap: 22px;
      margin-top: 22px;
    }}
    .panel {{
      padding: 22px;
    }}
    .panel h3 {{
      margin: 0 0 6px;
      font-size: 18px;
      letter-spacing: 0.02em;
    }}
    .panel p {{
      margin: 0 0 18px;
      color: var(--muted);
      line-height: 1.65;
      font-size: 14px;
    }}
    .chart-frame {{
      border-radius: 22px;
      background: linear-gradient(180deg, rgba(255,255,255,0.82), rgba(244,237,227,0.92));
      border: 1px solid rgba(18, 32, 51, 0.08);
      min-height: 320px;
      padding: 16px;
      overflow: hidden;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-top: 22px;
    }}
    .group-card {{
      border-radius: 22px;
      padding: 18px;
      background: linear-gradient(155deg, rgba(255,255,255,0.92), rgba(244,237,227,0.96));
      border: 1px solid rgba(18, 32, 51, 0.09);
      position: relative;
      overflow: hidden;
    }}
    .group-card::before {{
      content: "";
      position: absolute;
      inset: auto auto -40px -20px;
      width: 120px;
      height: 120px;
      border-radius: 50%;
      background: radial-gradient(circle, var(--card-color), transparent 70%);
      opacity: 0.18;
    }}
    .group-card h4 {{
      margin: 0 0 14px;
      font-size: 15px;
      max-width: 18ch;
      line-height: 1.35;
    }}
    .group-card dl {{
      margin: 0;
      display: grid;
      gap: 10px;
    }}
    .group-card div {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      font-size: 13px;
      color: var(--muted);
    }}
    .group-card dd, .group-card dt {{
      margin: 0;
    }}
    .table-wrap {{
      margin-top: 22px;
      overflow: auto;
      border-radius: 20px;
      border: 1px solid rgba(18, 32, 51, 0.08);
      background: rgba(255,255,255,0.74);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 980px;
    }}
    thead th {{
      position: sticky;
      top: 0;
      background: rgba(247, 242, 232, 0.96);
      z-index: 1;
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
    }}
    th, td {{
      padding: 12px 14px;
      border-bottom: 1px solid rgba(18, 32, 51, 0.07);
      text-align: left;
      font-size: 13px;
      white-space: nowrap;
    }}
    tbody tr:hover {{
      background: rgba(199, 84, 31, 0.05);
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 12px;
      letter-spacing: 0.04em;
      border: 1px solid transparent;
    }}
    .state-completed {{ background: rgba(13,138,114,0.12); color: #0d8a72; border-color: rgba(13,138,114,0.22); }}
    .state-running {{ background: rgba(199,84,31,0.12); color: #b24d1e; border-color: rgba(199,84,31,0.22); }}
    .state-pending {{ background: rgba(32,72,168,0.10); color: #2048a8; border-color: rgba(32,72,168,0.18); }}
    .footnote {{
      margin-top: 18px;
      font-size: 12px;
      color: var(--muted);
    }}
    @media (max-width: 1080px) {{
      .hero, .layout {{
        grid-template-columns: 1fr;
      }}
      .headline::after {{
        font-size: 42px;
        top: 22px;
        right: 10px;
      }}
    }}
    @media (max-width: 720px) {{
      .page {{ padding-inline: 14px; }}
      .headline, .summary-card, .panel {{ border-radius: 22px; }}
      .hero-metrics {{ grid-template-columns: 1fr 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <article class="headline">
        <span class="eyebrow">Loop Analytics</span>
        <h1>Round 统计图 已生成</h1>
        <p class="lede">这个页面聚焦 `project_id={html.escape(project_id)}` 的三 seed 实验。失败 round 已剔除；运行中 round 仍保留，并在最新可见指标不足时显示为空。整体视觉走“编辑型实验年鉴”路线，方便你直接截图或继续补充筛选。</p>
        <div class="hero-metrics">
          <div class="metric-chip"><strong>{len(round_rows)}</strong><span>非失败 Round</span></div>
          <div class="metric-chip"><strong>{len(group_cards)}</strong><span>三 Seed 实验组</span></div>
          <div class="metric-chip"><strong>{sum(1 for row in round_rows if row.state == "RUNNING")}</strong><span>运行中 Round</span></div>
          <div class="metric-chip"><strong>{sum(1 for row in round_rows if row.state == "PENDING")}</strong><span>待运行 Round</span></div>
        </div>
      </article>
      <aside class="summary-card">
        <div>
          <h2>Snapshot</h2>
          <p>生成时间 {html.escape(generated_at)}。mAP50_95 趋势图展示实验组均值，右侧明细表展示每个非失败 round 的实时状态与指标来源。</p>
        </div>
        <div class="score-strip">
          <div><span>Completed</span><b>{summary["completedRounds"]}</b></div>
          <div><span>Running</span><b>{summary["runningRounds"]}</b></div>
          <div><span>Pending</span><b>{summary["pendingRounds"]}</b></div>
        </div>
      </aside>
    </section>

    <section class="layout">
      <article class="panel">
        <h3>mAP50_95 均值轨迹</h3>
        <p>按三 seed 实验组聚合，每个点是该 round 的均值，阴影带表示标准差。空 round 不连线。</p>
        <div class="chart-frame"><svg id="mean-trend" width="100%" height="360" viewBox="0 0 860 360"></svg></div>
      </article>
      <article class="panel">
        <h3>最新状态条</h3>
        <p>每个组只看当前最新 round，色块分别表示 completed / running / pending 的 seed 数。</p>
        <div class="chart-frame"><svg id="status-bars" width="100%" height="360" viewBox="0 0 520 360"></svg></div>
      </article>
    </section>

    <section class="panel" style="margin-top:22px;">
      <h3>Seed 轨迹卡</h3>
      <p>每个小面板画出同组 3 条 seed 的 mAP50_95 轨迹，便于观察方差和某个 seed 的异常跃迁。</p>
      <div class="chart-frame"><svg id="seed-panels" width="100%" height="760" viewBox="0 0 1180 760"></svg></div>
      <div class="cards" id="group-cards"></div>
    </section>

    <section class="panel" style="margin-top:22px;">
      <h3>Round 明细</h3>
      <p>仅保留非失败 round。`metrics_source` 表示当前该 round 的指标来源：`eval / train / other / none`。</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>组别</th>
              <th>seed</th>
              <th>loop</th>
              <th>round</th>
              <th>state</th>
              <th>source</th>
              <th>mAP50</th>
              <th>mAP50_95</th>
              <th>precision</th>
              <th>recall</th>
              <th>loss</th>
              <th>selected</th>
              <th>revealed</th>
            </tr>
          </thead>
          <tbody id="detail-body"></tbody>
        </table>
      </div>
      <div class="footnote">导出的 TSV 与 SVG 已同时写入 `runs/reports/`。</div>
    </section>
  </main>

  <script>
    const summary = {json_dumps(summary)};
    const groups = {json_dumps(group_cards)};
    const aggregates = {json_dumps(dashboard_aggregates)};
    const roundRows = {json_dumps(dashboard_rows)};
    const groupColors = {json_dumps(GROUP_COLORS)};
    const seedColors = {json_dumps(SEED_COLORS)};

    const formatMetric = (value, digits = 4) => value == null ? "-" : Number(value).toFixed(digits);
    const escapeHtml = (value) => String(value ?? "").replace(/[&<>"]/g, (ch) => ({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"}}[ch]));
    const scaleLinear = (value, domainMin, domainMax, rangeMin, rangeMax) => {{
      if (domainMin === domainMax) return (rangeMin + rangeMax) / 2;
      return rangeMin + ((value - domainMin) / (domainMax - domainMin)) * (rangeMax - rangeMin);
    }};

    function renderCards() {{
      const root = document.getElementById("group-cards");
      root.innerHTML = groups.map((group) => `
        <article class="group-card" style="--card-color:${{group.color}}">
          <h4>${{escapeHtml(group.name)}}</h4>
          <dl>
            <div><dt>最新 round</dt><dd>r${{group.latestRound}}</dd></div>
            <div><dt>最新状态</dt><dd>${{escapeHtml(group.latestState)}}</dd></div>
            <div><dt>最新有指标的 round</dt><dd>${{group.latestMetricRound == null ? "-" : "r" + group.latestMetricRound}}</dd></div>
            <div><dt>最新 mAP50_95</dt><dd>${{formatMetric(group.latestMap5095)}}</dd></div>
            <div><dt>seed 覆盖</dt><dd>${{group.seedCoverage.join(", ")}}</dd></div>
          </dl>
        </article>
      `).join("");
    }}

    function renderMeanTrend() {{
      const svg = document.getElementById("mean-trend");
      const width = 860;
      const height = 360;
      const margin = {{ left: 68, right: 24, top: 20, bottom: 42 }};
      const plotWidth = width - margin.left - margin.right;
      const plotHeight = height - margin.top - margin.bottom;
      const maxRound = Math.max(...aggregates.map((row) => row.round_index), 1);
      const maxMetric = Math.max(...aggregates.map((row) => row.map50_95_mean || 0), 0.45);
      const upperMetric = Math.max(0.45, Math.ceil(maxMetric * 20) / 20);

      let parts = [`<rect width="${{width}}" height="${{height}}" rx="20" fill="rgba(255,255,255,0.42)"/>`];

      for (let i = 0; i <= 5; i += 1) {{
        const value = upperMetric * i / 5;
        const y = scaleLinear(value, 0, upperMetric, margin.top + plotHeight, margin.top);
        parts.push(`<line x1="${{margin.left}}" y1="${{y}}" x2="${{width - margin.right}}" y2="${{y}}" stroke="rgba(18,32,51,0.12)" />`);
        parts.push(`<text x="${{margin.left - 12}}" y="${{y + 4}}" text-anchor="end" fill="#6c6357" font-size="11">${{value.toFixed(2)}}</text>`);
      }}

      for (let roundIndex = 1; roundIndex <= maxRound; roundIndex += 1) {{
        const x = scaleLinear(roundIndex, 1, maxRound, margin.left, margin.left + plotWidth);
        parts.push(`<line x1="${{x}}" y1="${{margin.top}}" x2="${{x}}" y2="${{margin.top + plotHeight}}" stroke="rgba(18,32,51,0.08)" />`);
        parts.push(`<text x="${{x}}" y="${{height - 14}}" text-anchor="middle" fill="#6c6357" font-size="11">${{roundIndex}}</text>`);
      }}

      groups.forEach((group, idx) => {{
        const rows = aggregates.filter((row) => row.base_name === group.name && row.map50_95_mean != null).sort((a, b) => a.round_index - b.round_index);
        if (!rows.length) return;
        const color = group.color;
        const upperPoints = rows.map((row) => {{
          const x = scaleLinear(row.round_index, 1, maxRound, margin.left, margin.left + plotWidth);
          const y = scaleLinear((row.map50_95_mean || 0) + (row.map50_95_std || 0), 0, upperMetric, margin.top + plotHeight, margin.top);
          return [x, y];
        }});
        const lowerPoints = [...rows].reverse().map((row) => {{
          const x = scaleLinear(row.round_index, 1, maxRound, margin.left, margin.left + plotWidth);
          const y = scaleLinear(Math.max(0, (row.map50_95_mean || 0) - (row.map50_95_std || 0)), 0, upperMetric, margin.top + plotHeight, margin.top);
          return [x, y];
        }});
        const areaPath = [...upperPoints, ...lowerPoints].map(([x, y], pointIndex) => `${{pointIndex === 0 ? "M" : "L"}} ${{x}} ${{y}}`).join(" ") + " Z";
        parts.push(`<path d="${{areaPath}}" fill="${{color}}22" stroke="none"></path>`);

        const linePath = rows.map((row, pointIndex) => {{
          const x = scaleLinear(row.round_index, 1, maxRound, margin.left, margin.left + plotWidth);
          const y = scaleLinear(row.map50_95_mean || 0, 0, upperMetric, margin.top + plotHeight, margin.top);
          return `${{pointIndex === 0 ? "M" : "L"}} ${{x}} ${{y}}`;
        }}).join(" ");
        parts.push(`<path d="${{linePath}}" fill="none" stroke="${{color}}" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"></path>`);

        rows.forEach((row) => {{
          const x = scaleLinear(row.round_index, 1, maxRound, margin.left, margin.left + plotWidth);
          const y = scaleLinear(row.map50_95_mean || 0, 0, upperMetric, margin.top + plotHeight, margin.top);
          parts.push(`<circle cx="${{x}}" cy="${{y}}" r="4.5" fill="${{color}}" stroke="#fffdfa" stroke-width="1.5"></circle>`);
        }});

        const legendX = 590;
        const legendY = 28 + idx * 24;
        parts.push(`<line x1="${{legendX}}" y1="${{legendY}}" x2="${{legendX + 20}}" y2="${{legendY}}" stroke="${{color}}" stroke-width="3.5" stroke-linecap="round"></line>`);
        parts.push(`<text x="${{legendX + 28}}" y="${{legendY + 4}}" fill="#50463a" font-size="12">${{escapeHtml(group.name)}}</text>`);
      }});

      svg.innerHTML = parts.join("");
    }}

    function renderStatusBars() {{
      const svg = document.getElementById("status-bars");
      const width = 520;
      const height = 360;
      const barLeft = 190;
      const barWidth = 230;
      const rowTop = 28;
      const rowGap = 56;
      let parts = [`<rect width="${{width}}" height="${{height}}" rx="18" fill="rgba(255,255,255,0.35)"/>`];

      groups.forEach((group, index) => {{
        const rows = aggregates.filter((row) => row.base_name === group.name);
        if (!rows.length) return;
        const latest = rows.reduce((best, row) => row.round_index > best.round_index ? row : best, rows[0]);
        const y = rowTop + index * rowGap;
        parts.push(`<text x="0" y="${{y + 18}}" fill="#352d26" font-size="12" font-weight="700">${{escapeHtml(group.name)}}</text>`);
        parts.push(`<text x="0" y="${{y + 36}}" fill="#7a6f62" font-size="11">latest r${{latest.round_index}}</text>`);
        const total = Math.max(latest.seed_count, 1);
        const segments = [
          [latest.completed_count, "#0f8a72"],
          [latest.running_count, "#e07a2e"],
          [latest.pending_count, "#8095b2"],
        ];
        let x = barLeft;
        segments.forEach(([count, color]) => {{
          const segmentWidth = barWidth * count / total;
          if (segmentWidth <= 0) return;
          parts.push(`<rect x="${{x}}" y="${{y}}" width="${{segmentWidth}}" height="26" rx="9" fill="${{color}}"></rect>`);
          x += segmentWidth;
        }});
        parts.push(`<rect x="${{barLeft}}" y="${{y}}" width="${{barWidth}}" height="26" rx="9" fill="none" stroke="rgba(18,32,51,0.14)"></rect>`);
        parts.push(`<text x="${{barLeft + barWidth + 14}}" y="${{y + 18}}" fill="#655b50" font-size="12">C${{latest.completed_count}} / R${{latest.running_count}} / P${{latest.pending_count}}</text>`);
      }});
      svg.innerHTML = parts.join("");
    }}

    function renderSeedPanels() {{
      const svg = document.getElementById("seed-panels");
      const width = 1180;
      const height = 760;
      const panelCols = 2;
      const panelWidth = 540;
      const panelHeight = 210;
      const panelGapX = 36;
      const panelGapY = 28;
      const startX = 10;
      const startY = 10;
      let parts = [`<rect width="${{width}}" height="${{height}}" rx="20" fill="rgba(255,255,255,0.38)"/>`];

      groups.forEach((group, index) => {{
        const rowIndex = Math.floor(index / panelCols);
        const colIndex = index % panelCols;
        const x0 = startX + colIndex * (panelWidth + panelGapX);
        const y0 = startY + rowIndex * (panelHeight + panelGapY);
        parts.push(`<rect x="${{x0}}" y="${{y0}}" width="${{panelWidth}}" height="${{panelHeight}}" rx="20" fill="rgba(255,253,248,0.9)" stroke="rgba(18,32,51,0.08)"></rect>`);
        parts.push(`<text x="${{x0 + 16}}" y="${{y0 + 24}}" fill="#152338" font-size="14" font-weight="700">${{escapeHtml(group.name)}}</text>`);
        const rows = roundRows.filter((item) => item.base_name === group.name && item.seed);
        const maxRound = Math.max(...rows.map((item) => item.round_index), 1);
        const maxMetric = Math.max(...rows.map((item) => item.map50_95 || 0), 0.45);
        const upperMetric = Math.max(0.45, Math.ceil(maxMetric * 20) / 20);
        const left = x0 + 46;
        const right = x0 + panelWidth - 16;
        const top = y0 + 36;
        const bottom = y0 + panelHeight - 28;

        for (let i = 0; i <= 4; i += 1) {{
          const value = upperMetric * i / 4;
          const y = scaleLinear(value, 0, upperMetric, bottom, top);
          parts.push(`<line x1="${{left}}" y1="${{y}}" x2="${{right}}" y2="${{y}}" stroke="rgba(18,32,51,0.09)"></line>`);
        }}
        for (let roundIndex = 1; roundIndex <= maxRound; roundIndex += 1) {{
          const x = scaleLinear(roundIndex, 1, maxRound, left, right);
          parts.push(`<line x1="${{x}}" y1="${{top}}" x2="${{x}}" y2="${{bottom}}" stroke="rgba(18,32,51,0.06)"></line>`);
        }}

        ["1", "2", "3"].forEach((seed) => {{
          const seedRows = rows.filter((item) => item.seed === seed && item.map50_95 != null).sort((a, b) => a.round_index - b.round_index || a.attempt_index - b.attempt_index);
          if (!seedRows.length) return;
          const path = seedRows.map((item, pointIndex) => {{
            const x = scaleLinear(item.round_index, 1, maxRound, left, right);
            const y = scaleLinear(item.map50_95 || 0, 0, upperMetric, bottom, top);
            return `${{pointIndex === 0 ? "M" : "L"}} ${{x}} ${{y}}`;
          }}).join(" ");
          const color = seedColors[seed];
          parts.push(`<path d="${{path}}" fill="none" stroke="${{color}}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></path>`);
          const last = seedRows[seedRows.length - 1];
          const x = scaleLinear(last.round_index, 1, maxRound, left, right);
          const y = scaleLinear(last.map50_95 || 0, 0, upperMetric, bottom, top);
          parts.push(`<circle cx="${{x}}" cy="${{y}}" r="4" fill="${{color}}" stroke="#fffdfa" stroke-width="1.4"></circle>`);
          parts.push(`<text x="${{x + 7}}" y="${{y + 4}}" fill="${{color}}" font-size="11" font-weight="700">s${{seed}}</text>`);
        }});
      }});

      svg.innerHTML = parts.join("");
    }}

    function renderTable() {{
      const tbody = document.getElementById("detail-body");
      tbody.innerHTML = roundRows.map((row) => {{
        const stateClass = `state-${{String(row.state || "").toLowerCase()}}`;
        return `
          <tr>
            <td>${{escapeHtml(row.base_name)}}</td>
            <td>${{row.seed || "-"}}</td>
            <td>${{escapeHtml(row.loop_name)}}</td>
            <td>r${{row.round_index}}.${{row.attempt_index}}</td>
            <td><span class="badge ${{stateClass}}">${{escapeHtml(row.state)}}</span></td>
            <td>${{escapeHtml(row.metrics_source)}}</td>
            <td>${{formatMetric(row.map50)}}</td>
            <td>${{formatMetric(row.map50_95)}}</td>
            <td>${{formatMetric(row.precision)}}</td>
            <td>${{formatMetric(row.recall)}}</td>
            <td>${{formatMetric(row.loss)}}</td>
            <td>${{row.confirmed_selected_count}}</td>
            <td>${{row.confirmed_revealed_count}}</td>
          </tr>
        `;
      }}).join("");
    }}

    renderCards();
    renderMeanTrend();
    renderStatusBars();
    renderSeedPanels();
    renderTable();
  </script>
</body>
</html>
"""
    path.write_text(html_text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    password = os.environ.get(args.password_env, "")
    if not password:
        raise SystemExit(f"环境变量 {args.password_env} 为空，无法连接数据库。")

    psql = require_psql()
    env = dict(os.environ)
    env["PGPASSWORD"] = password

    loops = run_copy(
        psql=psql,
        env=env,
        host=args.host,
        port=args.port,
        user=args.user,
        database=args.database,
        query=f"""
SELECT
  l.id::text AS loop_id,
  l.name,
  COALESCE(b.name, '') AS branch_name,
  l.mode::text AS mode,
  l.phase::text AS phase,
  l.lifecycle::text AS lifecycle,
  l.current_iteration,
  COALESCE(l.config->'reproducibility'->>'global_seed','') AS global_seed,
  COALESCE(l.config->'reproducibility'->>'split_seed','') AS split_seed,
  COALESCE(l.config->'reproducibility'->>'train_seed','') AS train_seed,
  COALESCE(l.config->'reproducibility'->>'sampling_seed','') AS sampling_seed,
  to_char(l.created_at AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM-DD HH24:MI:SS') AS created_at_sh
FROM loop l
LEFT JOIN branch b ON b.id = l.branch_id
WHERE l.project_id = '{args.project_id}'
ORDER BY l.created_at
        """.strip(),
    )
    rounds = run_copy(
        psql=psql,
        env=env,
        host=args.host,
        port=args.port,
        user=args.user,
        database=args.database,
        query=f"""
SELECT
  r.id::text AS round_id,
  r.loop_id::text AS loop_id,
  r.round_index,
  r.attempt_index,
  r.state::text AS state,
  r.confirmed_revealed_count,
  r.confirmed_selected_count,
  r.confirmed_effective_min_required,
  COALESCE(r.final_metrics::text, '{{}}') AS round_final_metrics_json,
  to_char(r.started_at AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM-DD HH24:MI:SS') AS started_at_sh,
  to_char(r.ended_at AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM-DD HH24:MI:SS') AS ended_at_sh,
  to_char(r.created_at AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM-DD HH24:MI:SS') AS created_at_sh,
  COALESCE(r.terminal_reason, '') AS terminal_reason
FROM round r
WHERE r.project_id = '{args.project_id}'
ORDER BY r.loop_id, r.round_index, r.attempt_index, r.created_at
        """.strip(),
    )
    steps = run_copy(
        psql=psql,
        env=env,
        host=args.host,
        port=args.port,
        user=args.user,
        database=args.database,
        query=f"""
SELECT
  s.id::text AS step_id,
  s.round_id::text AS round_id,
  s.step_type::text AS step_type,
  s.state::text AS step_state,
  s.step_index,
  to_char(s.created_at AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM-DD HH24:MI:SS') AS step_created_at_sh,
  t.id::text AS task_id,
  t.status::text AS task_status,
  COALESCE((t.resolved_params->'_result_metrics')::text, '{{}}') AS result_metrics_json
FROM step s
JOIN round r ON r.id = s.round_id
JOIN task t ON t.id = s.task_id
WHERE r.project_id = '{args.project_id}'
ORDER BY s.round_id, s.step_index, s.created_at
        """.strip(),
    )

    round_rows, aggregate_rows, _ = build_round_rows(loops=loops, rounds=rounds, steps=steps)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.project_id.replace("-", "")[:8]
    tsv_path = out_dir / f"{stem}_loop_round_rows.tsv"
    dashboard_path = out_dir / f"{stem}_loop_round_dashboard.html"
    mean_svg_path = out_dir / f"{stem}_loop_round_mean_map50_95.svg"
    seed_svg_path = out_dir / f"{stem}_loop_round_seed_paths.svg"
    status_svg_path = out_dir / f"{stem}_loop_round_status.svg"

    write_tsv(tsv_path, round_rows)
    build_group_mean_svg(mean_svg_path, aggregate_rows)
    build_seed_small_multiples_svg(seed_svg_path, round_rows)
    build_status_svg(status_svg_path, aggregate_rows)
    build_dashboard_html(
        dashboard_path,
        project_id=args.project_id,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        round_rows=round_rows,
        aggregates=aggregate_rows,
    )

    print(json.dumps(
        {
            "dashboard": str(dashboard_path.resolve()),
            "tsv": str(tsv_path.resolve()),
            "mean_svg": str(mean_svg_path.resolve()),
            "seed_svg": str(seed_svg_path.resolve()),
            "status_svg": str(status_svg_path.resolve()),
            "round_count": len(round_rows),
            "aggregate_count": len(aggregate_rows),
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
