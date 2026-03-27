from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_HEADERS = [
    "experiment_group",
    "group_kind",
    "member_loop_count",
    "member_loops",
    "round_index",
    "included_result_count",
    "included_non_success_with_result_count",
    "excluded_no_result_count",
    "missing_loop_count",
    "map50_avg",
    "map50_std",
    "map50_95_avg",
    "map50_95_std",
    "precision_avg",
    "precision_std",
    "recall_avg",
    "recall_std",
    "notes",
]


def write_sample_stats_csv(path: Path) -> None:
    rows = [
        {
            "experiment_group": "sim-random",
            "group_kind": "seeded",
            "member_loop_count": "3",
            "member_loops": "sim-random-1; sim-random-2; sim-random-3",
            "round_index": "1",
            "included_result_count": "3",
            "included_non_success_with_result_count": "0",
            "excluded_no_result_count": "0",
            "missing_loop_count": "0",
            "map50_avg": "0.100000",
            "map50_std": "0.010000",
            "map50_95_avg": "0.060000",
            "map50_95_std": "0.008000",
            "precision_avg": "0.210000",
            "precision_std": "0.010000",
            "recall_avg": "0.120000",
            "recall_std": "0.020000",
            "notes": "",
        },
        {
            "experiment_group": "sim-random",
            "group_kind": "seeded",
            "member_loop_count": "3",
            "member_loops": "sim-random-1; sim-random-2; sim-random-3",
            "round_index": "2",
            "included_result_count": "3",
            "included_non_success_with_result_count": "0",
            "excluded_no_result_count": "0",
            "missing_loop_count": "0",
            "map50_avg": "0.160000",
            "map50_std": "0.012000",
            "map50_95_avg": "0.100000",
            "map50_95_std": "0.009000",
            "precision_avg": "0.300000",
            "precision_std": "0.010000",
            "recall_avg": "0.200000",
            "recall_std": "0.010000",
            "notes": "",
        },
        {
            "experiment_group": "sim-uncertainty",
            "group_kind": "seeded",
            "member_loop_count": "3",
            "member_loops": "sim-uncertainty-1; sim-uncertainty-2; sim-uncertainty-3",
            "round_index": "1",
            "included_result_count": "3",
            "included_non_success_with_result_count": "0",
            "excluded_no_result_count": "0",
            "missing_loop_count": "0",
            "map50_avg": "0.110000",
            "map50_std": "0.009000",
            "map50_95_avg": "0.070000",
            "map50_95_std": "0.007000",
            "precision_avg": "0.220000",
            "precision_std": "0.010000",
            "recall_avg": "0.130000",
            "recall_std": "0.020000",
            "notes": "",
        },
        {
            "experiment_group": "sim-uncertainty",
            "group_kind": "seeded",
            "member_loop_count": "3",
            "member_loops": "sim-uncertainty-1; sim-uncertainty-2; sim-uncertainty-3",
            "round_index": "2",
            "included_result_count": "3",
            "included_non_success_with_result_count": "0",
            "excluded_no_result_count": "0",
            "missing_loop_count": "0",
            "map50_avg": "0.180000",
            "map50_std": "0.011000",
            "map50_95_avg": "0.120000",
            "map50_95_std": "0.008000",
            "precision_avg": "0.320000",
            "precision_std": "0.010000",
            "recall_avg": "0.220000",
            "recall_std": "0.010000",
            "notes": "",
        },
        {
            "experiment_group": "sim-aug_iou-rect",
            "group_kind": "seeded",
            "member_loop_count": "3",
            "member_loops": "sim-aug_iou-rect-1; sim-aug_iou-rect-2; sim-aug_iou-rect-3",
            "round_index": "1",
            "included_result_count": "3",
            "included_non_success_with_result_count": "0",
            "excluded_no_result_count": "0",
            "missing_loop_count": "0",
            "map50_avg": "0.140000",
            "map50_std": "0.010000",
            "map50_95_avg": "0.090000",
            "map50_95_std": "0.006000",
            "precision_avg": "0.250000",
            "precision_std": "0.010000",
            "recall_avg": "0.170000",
            "recall_std": "0.010000",
            "notes": "",
        },
        {
            "experiment_group": "sim-aug_iou-rect",
            "group_kind": "seeded",
            "member_loop_count": "3",
            "member_loops": "sim-aug_iou-rect-1; sim-aug_iou-rect-2; sim-aug_iou-rect-3",
            "round_index": "2",
            "included_result_count": "3",
            "included_non_success_with_result_count": "0",
            "excluded_no_result_count": "0",
            "missing_loop_count": "0",
            "map50_avg": "0.220000",
            "map50_std": "0.013000",
            "map50_95_avg": "0.150000",
            "map50_95_std": "0.007000",
            "precision_avg": "0.350000",
            "precision_std": "0.010000",
            "recall_avg": "0.250000",
            "recall_std": "0.010000",
            "notes": "",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SAMPLE_HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def test_generate_paper_strategy_tables_accepts_custom_groups(tmp_path: Path) -> None:
    stats_csv = tmp_path / "stats.csv"
    output_md = tmp_path / "tables.md"
    output_tex = tmp_path / "tables.tex"
    write_sample_stats_csv(stats_csv)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/generate_paper_strategy_tables.py",
            "--stats-csv",
            str(stats_csv),
            "--output-md",
            str(output_md),
            "--output-tex",
            str(output_tex),
            "--groups",
            "sim-random,sim-uncertainty,sim-aug_iou-rect",
            "--display-names",
            "Random,Uncertainty,Aug-Rect",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert output_md.exists()
    assert output_tex.exists()
    content = output_md.read_text(encoding="utf-8")
    assert "Aug-Rect" in content
    assert "Uncertainty" in content


def test_render_paper_selected_strategy_band_chart_accepts_custom_groups(tmp_path: Path) -> None:
    stats_csv = tmp_path / "stats.csv"
    output_svg = tmp_path / "chart.svg"
    write_sample_stats_csv(stats_csv)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/render_paper_selected_strategy_band_chart.py",
            "--stats-csv",
            str(stats_csv),
            "--output",
            str(output_svg),
            "--metric",
            "map50_95",
            "--theme",
            "color",
            "--groups",
            "sim-random,sim-uncertainty,sim-aug_iou-rect",
            "--display-names",
            "Random,Uncertainty,Aug-Rect",
            "--colors",
            "#1b7f6b,#6b7280,#b7791f",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert output_svg.exists()
    content = output_svg.read_text(encoding="utf-8")
    assert "Random" in content
    assert "Aug-Rect" in content
