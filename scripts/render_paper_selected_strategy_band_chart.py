#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


DEFAULT_SELECTED_GROUPS = [
    "sim-aug-boundary-yolov8l",
    "sim-aug-obb-yolov8l",
    "sim-aug-rect-yolov8l",
    "sim-random-yolov8l",
    "sim-uncertainty-yolov8l",
]

DEFAULT_DISPLAY_NAMES = {
    "sim-aug-boundary-yolov8l": "aug_iou(boundary)",
    "sim-aug-obb-yolov8l": "aug_iou(obb)",
    "sim-aug-rect-yolov8l": "aug_iou(rect)",
    "sim-random-yolov8l": "random",
    "sim-uncertainty-yolov8l": "uncertainty",
}

DEFAULT_GROUP_COLORS = {
    "sim-aug-boundary-yolov8l": "#0f4c81",
    "sim-aug-obb-yolov8l": "#b23a48",
    "sim-aug-rect-yolov8l": "#b7791f",
    "sim-random-yolov8l": "#1b7f6b",
    "sim-uncertainty-yolov8l": "#6b7280",
}

DEFAULT_GROUP_GRAYS = {
    "sim-aug-boundary-yolov8l": "#111111",
    "sim-aug-obb-yolov8l": "#333333",
    "sim-aug-rect-yolov8l": "#555555",
    "sim-random-yolov8l": "#777777",
    "sim-uncertainty-yolov8l": "#999999",
}

DEFAULT_GROUP_DASHES = {
    "sim-aug-boundary-yolov8l": "",
    "sim-aug-obb-yolov8l": "10 5",
    "sim-aug-rect-yolov8l": "4 4",
    "sim-random-yolov8l": "14 6 4 6",
    "sim-uncertainty-yolov8l": "2 4",
}

FALLBACK_COLORS = [
    "#0f4c81",
    "#b23a48",
    "#b7791f",
    "#1b7f6b",
    "#6b7280",
    "#8f5ea2",
]

FALLBACK_GRAYS = [
    "#111111",
    "#333333",
    "#555555",
    "#777777",
    "#999999",
    "#bbbbbb",
]

FALLBACK_DASHES = [
    "",
    "10 5",
    "4 4",
    "14 6 4 6",
    "2 4",
    "8 4 2 4",
]


@dataclass(frozen=True)
class StatRow:
    experiment_group: str
    round_index: int
    map50_avg: float | None
    map50_std: float | None
    map50_95_avg: float | None
    map50_95_std: float | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a paper-ready selected strategy band chart.")
    parser.add_argument("--stats-csv", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--metric", choices=("map50_95", "map50"), required=True)
    parser.add_argument("--theme", choices=("color", "bw"), default="color")
    parser.add_argument("--groups", default=",".join(DEFAULT_SELECTED_GROUPS))
    parser.add_argument("--display-names", default="")
    parser.add_argument("--colors", default="")
    return parser.parse_args()


def parse_csv_arg(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def resolve_plot_config(
    args: argparse.Namespace,
) -> tuple[list[str], dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    groups = parse_csv_arg(args.groups)
    if not groups:
        raise SystemExit("至少需要通过 --groups 指定一个实验组。")

    custom_display_names = parse_csv_arg(args.display_names)
    if custom_display_names and len(custom_display_names) != len(groups):
        raise SystemExit("--display-names 的数量必须与 --groups 一致。")

    custom_colors = parse_csv_arg(args.colors)
    if custom_colors and len(custom_colors) != len(groups):
        raise SystemExit("--colors 的数量必须与 --groups 一致。")

    display_names: dict[str, str] = {}
    colors: dict[str, str] = {}
    grays: dict[str, str] = {}
    dashes: dict[str, str] = {}
    for index, group in enumerate(groups):
        display_names[group] = (
            custom_display_names[index]
            if custom_display_names
            else DEFAULT_DISPLAY_NAMES.get(group, group)
        )
        colors[group] = (
            custom_colors[index]
            if custom_colors
            else DEFAULT_GROUP_COLORS.get(group, FALLBACK_COLORS[index % len(FALLBACK_COLORS)])
        )
        grays[group] = DEFAULT_GROUP_GRAYS.get(group, FALLBACK_GRAYS[index % len(FALLBACK_GRAYS)])
        dashes[group] = DEFAULT_GROUP_DASHES.get(group, FALLBACK_DASHES[index % len(FALLBACK_DASHES)])
    return groups, display_names, colors, grays, dashes


def parse_float(value: str) -> float | None:
    text = (value or "").strip()
    if not text:
        return None
    return float(text)


def load_rows(path: Path, groups: list[str]) -> dict[str, list[StatRow]]:
    rows_by_group: dict[str, list[StatRow]] = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            group_name = row["experiment_group"]
            if group_name not in groups:
                continue
            rows_by_group[group_name].append(
                StatRow(
                    experiment_group=group_name,
                    round_index=int(row["round_index"]),
                    map50_avg=parse_float(row["map50_avg"]),
                    map50_std=parse_float(row["map50_std"]),
                    map50_95_avg=parse_float(row["map50_95_avg"]),
                    map50_95_std=parse_float(row["map50_95_std"]),
                )
            )
    for rows in rows_by_group.values():
        rows.sort(key=lambda item: item.round_index)
    return rows_by_group


def scale_linear(value: float, domain_min: float, domain_max: float, range_min: float, range_max: float) -> float:
    if math.isclose(domain_min, domain_max):
        return (range_min + range_max) / 2.0
    ratio = (value - domain_min) / (domain_max - domain_min)
    return range_min + ratio * (range_max - range_min)


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
    padding = max(0.01, (upper - lower) * 0.10)
    return max(0.0, lower - padding), min(1.0, upper + padding)


def line_path(points: list[tuple[float, float]]) -> str:
    return " ".join(
        f'{"M" if index == 0 else "L"} {x:.1f} {y:.1f}'
        for index, (x, y) in enumerate(points)
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


def svg_text(
    x: float,
    y: float,
    text: str,
    *,
    size: int = 14,
    fill: str = "#111827",
    anchor: str = "start",
    weight: int = 400,
    family: str = "'Times New Roman', 'Noto Serif', serif",
) -> str:
    escaped = html.escape(text)
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" font-size="{size}" '
        f'font-family="{family}" font-weight="{weight}" text-anchor="{anchor}">{escaped}</text>'
    )


def group_stroke(group_name: str, theme: str, *, colors: dict[str, str], grays: dict[str, str]) -> str:
    if theme == "bw":
        return grays[group_name]
    return colors[group_name]


def group_dash(group_name: str, theme: str, *, dashes: dict[str, str]) -> str:
    if theme == "bw":
        return dashes[group_name]
    return ""


def draw_metric_panel(
    *,
    lines: list[str],
    rows_by_group: dict[str, list[StatRow]],
    x: float,
    y: float,
    width: float,
    height: float,
    avg_attr: str,
    std_attr: str,
    title: str,
    theme: str,
    groups: list[str],
    colors: dict[str, str],
    grays: dict[str, str],
    dashes: dict[str, str],
) -> None:
    plot_x = x + 78
    plot_y = y + 34
    plot_w = width - 114
    plot_h = height - 104
    lower, upper = metric_domain(rows_by_group, avg_attr, std_attr)
    max_round = max(max(row.round_index for row in rows) for rows in rows_by_group.values())

    lines.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}" fill="white" stroke="#d1d5db" stroke-width="1"/>')
    lines.append(svg_text(x + 10, y + 22, title, size=17, weight=600))

    for step in range(6):
        value = lower + (upper - lower) * step / 5
        grid_y = scale_linear(value, lower, upper, plot_y + plot_h, plot_y)
        lines.append(f'<line x1="{plot_x:.1f}" y1="{grid_y:.1f}" x2="{plot_x + plot_w:.1f}" y2="{grid_y:.1f}" stroke="#e5e7eb" stroke-width="1"/>')
        lines.append(svg_text(plot_x - 10, grid_y + 4, f"{value:.2f}", size=11, fill="#4b5563", anchor="end", family="'Times New Roman', serif"))

    for round_index in range(1, max_round + 1):
        grid_x = scale_linear(round_index, 1, max_round, plot_x, plot_x + plot_w)
        lines.append(f'<line x1="{grid_x:.1f}" y1="{plot_y:.1f}" x2="{grid_x:.1f}" y2="{plot_y + plot_h:.1f}" stroke="#f3f4f6" stroke-width="1"/>')
        lines.append(svg_text(grid_x, plot_y + plot_h + 20, str(round_index), size=11, fill="#4b5563", anchor="middle", family="'Times New Roman', serif"))

    lines.append(f'<line x1="{plot_x:.1f}" y1="{plot_y:.1f}" x2="{plot_x:.1f}" y2="{plot_y + plot_h:.1f}" stroke="#374151" stroke-width="1.2"/>')
    lines.append(f'<line x1="{plot_x:.1f}" y1="{plot_y + plot_h:.1f}" x2="{plot_x + plot_w:.1f}" y2="{plot_y + plot_h:.1f}" stroke="#374151" stroke-width="1.2"/>')
    lines.append(svg_text(plot_x + plot_w / 2, y + height - 18, "Round", size=12, fill="#111827", anchor="middle"))

    for group_name in groups:
        color = group_stroke(group_name, theme, colors=colors, grays=grays)
        dash = group_dash(group_name, theme, dashes=dashes)
        upper_points: list[tuple[float, float]] = []
        lower_points: list[tuple[float, float]] = []
        avg_points: list[tuple[float, float]] = []
        for row in rows_by_group[group_name]:
            avg = getattr(row, avg_attr)
            if avg is None:
                continue
            std = getattr(row, std_attr) or 0.0
            px = scale_linear(row.round_index, 1, max_round, plot_x, plot_x + plot_w)
            py_avg = scale_linear(avg, lower, upper, plot_y + plot_h, plot_y)
            py_upper = scale_linear(avg + std, lower, upper, plot_y + plot_h, plot_y)
            py_lower = scale_linear(avg - std, lower, upper, plot_y + plot_h, plot_y)
            avg_points.append((px, py_avg))
            upper_points.append((px, py_upper))
            lower_points.append((px, py_lower))
        band = band_path(upper_points, lower_points)
        if band:
            band_opacity = "0.08" if theme == "bw" else "0.12"
            lines.append(f'<path d="{band}" fill="{color}" opacity="{band_opacity}"/>')
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        lines.append(
            f'<path d="{line_path(avg_points)}" fill="none" stroke="{color}" stroke-width="2.6" '
            f'stroke-linecap="round" stroke-linejoin="round"{dash_attr}/>'
        )


def build_svg(
    rows_by_group: dict[str, list[StatRow]],
    *,
    metric: str,
    theme: str,
    groups: list[str],
    display_names: dict[str, str],
    colors: dict[str, str],
    grays: dict[str, str],
    dashes: dict[str, str],
) -> str:
    width = 1250
    height = 750
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none">',
        f'<rect width="{width}" height="{height}" fill="white"/>',
    ]

    legend_x = 82
    legend_y = 58
    legend_gap = 225
    for index, group_name in enumerate(groups):
        x = legend_x + index * legend_gap
        y = legend_y
        color = group_stroke(group_name, theme, colors=colors, grays=grays)
        dash = group_dash(group_name, theme, dashes=dashes)
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        lines.append(
            f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x + 30:.1f}" y2="{y:.1f}" '
            f'stroke="{color}" stroke-width="3.5" stroke-linecap="round"{dash_attr}/>'
        )
        lines.append(svg_text(x + 38, y + 4, display_names[group_name], size=14, fill="#111827", family="'Times New Roman', serif"))

    if metric == "map50_95":
        avg_attr = "map50_95_avg"
        std_attr = "map50_95_std"
        title = "mAP50_95 (mean ± std)"
    else:
        avg_attr = "map50_avg"
        std_attr = "map50_std"
        title = "mAP50 (mean ± std)"

    draw_metric_panel(
        lines=lines,
        rows_by_group=rows_by_group,
        x=72,
        y=110,
        width=1106,
        height=560,
        avg_attr=avg_attr,
        std_attr=std_attr,
        title=title,
        theme=theme,
        groups=groups,
        colors=colors,
        grays=grays,
        dashes=dashes,
    )

    lines.append("</svg>")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    groups, display_names, colors, grays, dashes = resolve_plot_config(args)
    rows_by_group = load_rows(Path(args.stats_csv), groups)
    missing = [group_name for group_name in groups if group_name not in rows_by_group]
    if missing:
        raise SystemExit(f"统计 CSV 缺少实验组: {', '.join(missing)}")
    svg = build_svg(
        rows_by_group,
        metric=args.metric,
        theme=args.theme,
        groups=groups,
        display_names=display_names,
        colors=colors,
        grays=grays,
        dashes=dashes,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svg, encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
