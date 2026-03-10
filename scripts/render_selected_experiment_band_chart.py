#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


SELECTED_GROUPS = [
    "sim-random-yolov8l",
    "sim-uncertainty-yolov8l",
    "sim-aug-rect-yolov8l",
    "sim-aug-obb-yolov8l",
    "sim-aug-boundary-yolov8l",
]

GROUP_COLORS = {
    "sim-random-yolov8l": "#0d8a72",
    "sim-uncertainty-yolov8l": "#cf5c36",
    "sim-aug-rect-yolov8l": "#c18c18",
    "sim-aug-obb-yolov8l": "#b11c47",
    "sim-aug-boundary-yolov8l": "#1f4db6",
}


@dataclass(frozen=True)
class StatRow:
    experiment_group: str
    round_index: int
    included_result_count: int
    included_non_success_with_result_count: int
    excluded_no_result_count: int
    map50_avg: float | None
    map50_std: float | None
    map50_95_avg: float | None
    map50_95_std: float | None
    notes: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render selected experiment avg/std dashboard as SVG.")
    parser.add_argument("--stats-csv", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def parse_float(value: str) -> float | None:
    text = (value or "").strip()
    if not text:
        return None
    return float(text)


def load_rows(path: Path) -> dict[str, list[StatRow]]:
    rows_by_group: dict[str, list[StatRow]] = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            group_name = row["experiment_group"]
            if group_name not in SELECTED_GROUPS:
                continue
            rows_by_group[group_name].append(
                StatRow(
                    experiment_group=group_name,
                    round_index=int(row["round_index"]),
                    included_result_count=int(row["included_result_count"]),
                    included_non_success_with_result_count=int(row["included_non_success_with_result_count"]),
                    excluded_no_result_count=int(row["excluded_no_result_count"]),
                    map50_avg=parse_float(row["map50_avg"]),
                    map50_std=parse_float(row["map50_std"]),
                    map50_95_avg=parse_float(row["map50_95_avg"]),
                    map50_95_std=parse_float(row["map50_95_std"]),
                    notes=row["notes"],
                )
            )
    for rows in rows_by_group.values():
        rows.sort(key=lambda item: item.round_index)
    return rows_by_group


def scale_linear(value: float, domain_min: float, domain_max: float, range_min: float, range_max: float) -> float:
    if math.isclose(domain_min, domain_max):
        return (range_min + range_max) / 2
    ratio = (value - domain_min) / (domain_max - domain_min)
    return range_min + ratio * (range_max - range_min)


def svg_text(
    x: float,
    y: float,
    text: str,
    *,
    size: int = 14,
    fill: str = "#0f1724",
    anchor: str = "start",
    weight: int = 500,
    opacity: float = 1.0,
    family: str = "'Avenir Next', 'Trebuchet MS', sans-serif",
) -> str:
    escaped = html.escape(text)
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" font-size="{size}" '
        f'font-family="{family}" font-weight="{weight}" text-anchor="{anchor}" '
        f'opacity="{opacity:.2f}">{escaped}</text>'
    )


def svg_card(x: float, y: float, width: float, height: float, fill: str, stroke: str, opacity: float = 1.0) -> str:
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}" '
        f'rx="24" fill="{fill}" stroke="{stroke}" stroke-width="1.2" opacity="{opacity:.2f}"/>'
    )


def metric_domain(rows_by_group: dict[str, list[StatRow]], avg_attr: str, std_attr: str) -> tuple[float, float]:
    values: list[float] = []
    for rows in rows_by_group.values():
        for row in rows:
            avg = getattr(row, avg_attr)
            if avg is None:
                continue
            std = getattr(row, std_attr) or 0.0
            values.append(avg - std)
            values.append(avg + std)
    if not values:
        return 0.0, 1.0
    lower = min(values)
    upper = max(values)
    padding = max(0.015, (upper - lower) * 0.12)
    lower = max(0.0, lower - padding)
    upper = min(1.0, upper + padding)
    return lower, upper


def line_path(points: list[tuple[float, float]]) -> str:
    return " ".join(
        f'{"M" if idx == 0 else "L"} {x:.1f} {y:.1f}'
        for idx, (x, y) in enumerate(points)
    )


def band_path(upper_points: list[tuple[float, float]], lower_points: list[tuple[float, float]]) -> str:
    if not upper_points or not lower_points:
        return ""
    path = [f"M {upper_points[0][0]:.1f} {upper_points[0][1]:.1f}"]
    for x, y in upper_points[1:]:
        path.append(f"L {x:.1f} {y:.1f}")
    for x, y in reversed(lower_points):
        path.append(f"L {x:.1f} {y:.1f}")
    path.append("Z")
    return " ".join(path)


def draw_metric_panel(
    *,
    lines: list[str],
    x: float,
    y: float,
    width: float,
    height: float,
    rows_by_group: dict[str, list[StatRow]],
    avg_attr: str,
    std_attr: str,
    title: str,
    subtitle: str,
) -> None:
    lines.append(svg_card(x, y, width, height, "rgba(246,241,232,0.94)", "rgba(255,255,255,0.12)"))
    lines.append(svg_text(x + 28, y + 36, title, size=24, fill="#1f2b3f", weight=700, family="'Iowan Old Style', 'Palatino Linotype', serif"))
    lines.append(svg_text(x + 28, y + 64, subtitle, size=13, fill="#7b6f62", weight=500))

    plot_x = x + 72
    plot_y = y + 92
    plot_w = width - 104
    plot_h = height - 146

    lower, upper = metric_domain(rows_by_group, avg_attr, std_attr)
    max_round = max(max(row.round_index for row in rows) for rows in rows_by_group.values())

    for step in range(6):
        value = lower + (upper - lower) * step / 5
        grid_y = scale_linear(value, lower, upper, plot_y + plot_h, plot_y)
        lines.append(f'<line x1="{plot_x:.1f}" y1="{grid_y:.1f}" x2="{plot_x + plot_w:.1f}" y2="{grid_y:.1f}" stroke="rgba(255,255,255,0.10)" stroke-width="1"/>')
        lines.append(svg_text(plot_x - 14, grid_y + 4, f"{value:.2f}", size=12, fill="#a99c8f", anchor="end"))

    for round_index in range(1, max_round + 1):
        grid_x = scale_linear(round_index, 1, max_round, plot_x, plot_x + plot_w)
        lines.append(f'<line x1="{grid_x:.1f}" y1="{plot_y:.1f}" x2="{grid_x:.1f}" y2="{plot_y + plot_h:.1f}" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>')
        lines.append(svg_text(grid_x, plot_y + plot_h + 24, str(round_index), size=11, fill="#9d9185", anchor="middle"))

    for group_name in SELECTED_GROUPS:
        rows = rows_by_group[group_name]
        color = GROUP_COLORS[group_name]
        upper_points: list[tuple[float, float]] = []
        lower_points: list[tuple[float, float]] = []
        avg_points: list[tuple[float, float]] = []
        failed_rounds: list[tuple[int, int]] = []
        for row in rows:
            avg = getattr(row, avg_attr)
            if avg is None:
                continue
            std = getattr(row, std_attr) or 0.0
            px = scale_linear(row.round_index, 1, max_round, plot_x, plot_x + plot_w)
            upper_y = scale_linear(avg + std, lower, upper, plot_y + plot_h, plot_y)
            lower_y = scale_linear(avg - std, lower, upper, plot_y + plot_h, plot_y)
            avg_y = scale_linear(avg, lower, upper, plot_y + plot_h, plot_y)
            upper_points.append((px, upper_y))
            lower_points.append((px, lower_y))
            avg_points.append((px, avg_y))
            if row.excluded_no_result_count > 0:
                failed_rounds.append((row.round_index, row.excluded_no_result_count))

        band = band_path(upper_points, lower_points)
        if band:
            lines.append(f'<path d="{band}" fill="{color}" opacity="0.12"/>')
        lines.append(f'<path d="{line_path(avg_points)}" stroke="{color}" stroke-width="3.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>')
        for px, py in avg_points:
            lines.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.8" fill="{color}" stroke="#0f1724" stroke-width="1.5"/>')

        for round_index, failed_count in failed_rounds:
            px = scale_linear(round_index, 1, max_round, plot_x, plot_x + plot_w)
            marker_y = plot_y + plot_h + 42
            lines.append(f'<circle cx="{px:.1f}" cy="{marker_y:.1f}" r="10" fill="{color}" opacity="0.18"/>')
            lines.append(f'<circle cx="{px:.1f}" cy="{marker_y:.1f}" r="9.2" fill="none" stroke="{color}" stroke-width="1.2" opacity="0.75"/>')
            lines.append(svg_text(px, marker_y + 4, str(failed_count), size=10, fill=color, anchor="middle", weight=700))

    lines.append(svg_text(plot_x, y + height - 22, "圆点下方的小圆标记表示该 round 有被排除的无结果 seed 数。", size=12, fill="#9d9185"))


def build_svg(rows_by_group: dict[str, list[StatRow]]) -> str:
    width = 1600
    height = 1220
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none">',
        "<defs>",
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">',
        '<stop offset="0%" stop-color="#0d1726"/>',
        '<stop offset="54%" stop-color="#121d31"/>',
        '<stop offset="100%" stop-color="#1a2433"/>',
        "</linearGradient>",
        '<linearGradient id="wash" x1="0" y1="0" x2="1" y2="1">',
        '<stop offset="0%" stop-color="#c79b5d" stop-opacity="0.14"/>',
        '<stop offset="100%" stop-color="#5e7db3" stop-opacity="0.05"/>',
        "</linearGradient>",
        '<filter id="softShadow" x="-20%" y="-20%" width="140%" height="140%">',
        '<feDropShadow dx="0" dy="18" stdDeviation="22" flood-color="#02060d" flood-opacity="0.38"/>',
        "</filter>",
        "</defs>",
        f'<rect width="{width}" height="{height}" rx="34" fill="url(#bg)"/>',
        f'<rect x="18" y="18" width="{width - 36}" height="{height - 36}" rx="28" fill="url(#wash)" stroke="rgba(255,255,255,0.10)" stroke-width="1"/>',
        svg_text(56, 72, "Selected AL Strategies", size=34, fill="#f7f0e7", weight=700, family="'Iowan Old Style', 'Palatino Linotype', serif"),
        svg_text(56, 104, "同一实验设定下的五组策略，仅保留最后一次 attempt；每个 round 只要任一 seed 有结果就保留，阴影带为 avg ± std。", size=15, fill="#d0c4b8"),
    ]

    legend_x = 58
    legend_y = 136
    for idx, group_name in enumerate(SELECTED_GROUPS):
        y = legend_y + idx * 26
        color = GROUP_COLORS[group_name]
        lines.append(f'<line x1="{legend_x:.1f}" y1="{y:.1f}" x2="{legend_x + 22:.1f}" y2="{y:.1f}" stroke="{color}" stroke-width="5" stroke-linecap="round"/>')
        lines.append(svg_text(legend_x + 34, y + 4, group_name, size=13, fill="#ece2d8"))

    draw_metric_panel(
        lines=lines,
        x=42,
        y=196,
        width=1040,
        height=458,
        rows_by_group=rows_by_group,
        avg_attr="map50_95_avg",
        std_attr="map50_95_std",
        title="mAP50_95 Avg / Std",
        subtitle="主比较指标，越高越好。带状区域表示 seed 间波动。",
    )
    draw_metric_panel(
        lines=lines,
        x=42,
        y=694,
        width=1040,
        height=458,
        rows_by_group=rows_by_group,
        avg_attr="map50_avg",
        std_attr="map50_std",
        title="mAP50 Avg / Std",
        subtitle="补充查看高 IoU 之外的整体检测表现。",
    )

    card_x = 1118
    card_y = 196
    card_w = 438
    card_h = 180
    for idx, group_name in enumerate(SELECTED_GROUPS):
        y = card_y + idx * (card_h + 16)
        rows = rows_by_group[group_name]
        color = GROUP_COLORS[group_name]
        last_row = rows[-1]
        best_row = max((row for row in rows if row.map50_95_avg is not None), key=lambda item: item.map50_95_avg or -1.0)
        fail_total = sum(row.excluded_no_result_count for row in rows)
        fail_rounds = [str(row.round_index) for row in rows if row.excluded_no_result_count > 0]
        non_success_included = sum(row.included_non_success_with_result_count for row in rows)

        lines.append(f'<g filter="url(#softShadow)">')
        lines.append(svg_card(card_x, y, card_w, card_h, "rgba(244,239,231,0.96)", "rgba(255,255,255,0.08)"))
        lines.append(f'<rect x="{card_x + 16:.1f}" y="{y + 18:.1f}" width="10" height="{card_h - 36:.1f}" rx="5" fill="{color}"/>')
        lines.append(svg_text(card_x + 42, y + 38, group_name, size=18, fill="#182235", weight=700))
        lines.append(svg_text(card_x + 42, y + 66, f"final r{last_row.round_index} mAP50_95 avg {last_row.map50_95_avg:.4f}", size=13, fill="#485569"))
        lines.append(svg_text(card_x + 42, y + 88, f"final r{last_row.round_index} mAP50 avg {last_row.map50_avg:.4f}", size=13, fill="#485569"))
        lines.append(svg_text(card_x + 42, y + 116, f"peak r{best_row.round_index} mAP50_95 avg {best_row.map50_95_avg:.4f}", size=13, fill="#485569"))
        if fail_total > 0:
            fail_text = f"排除无结果 {fail_total} 次，涉及 round " + ", ".join(fail_rounds)
        else:
            fail_text = "无被排除的无结果 test"
        lines.append(svg_text(card_x + 42, y + 146, fail_text, size=12, fill="#7d4734" if fail_total > 0 else "#5b6b53", weight=600))
        if non_success_included > 0:
            lines.append(svg_text(card_x + 42, y + 164, f"非成功态但有结果并纳入 {non_success_included} 次", size=11, fill="#765b1c", weight=600))
        else:
            lines.append(svg_text(card_x + 42, y + 164, "当前没有非成功态但有结果的 test", size=11, fill="#6d6a55", weight=500))
        lines.append(f'</g>')

    footer = "输入来自按 round 聚合后的 EVAL 统计 CSV；同一 round 只要任一 seed 有结果就保留，avg/std 仅按有结果的 seed 计算。"
    lines.append(svg_text(56, height - 28, footer, size=12, fill="#9d9185"))
    lines.append("</svg>")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    rows_by_group = load_rows(Path(args.stats_csv))
    missing = [group_name for group_name in SELECTED_GROUPS if group_name not in rows_by_group]
    if missing:
        raise SystemExit(f"统计 CSV 缺少实验组: {', '.join(missing)}")

    svg = build_svg(rows_by_group)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svg, encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
