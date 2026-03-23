from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from obb_baseline.summary import (
    collect_suite_outputs,
    render_summary_markdown,
    write_suite_outputs,
)


def write_metrics(
    *,
    benchmark_root: Path,
    model_name: str,
    split_seed: int,
    train_seed: int,
    m_ap50_95: float,
    precision: float,
    recall: float,
) -> None:
    metrics_path = (
        benchmark_root
        / "records"
        / model_name
        / f"split-{split_seed}"
        / f"seed-{train_seed}"
        / "metrics.json"
    )
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mAP50_95": m_ap50_95,
        "precision": precision,
        "recall": recall,
        "extra_note": "allow-empty-field-check",
    }
    metrics_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_collect_suite_outputs_aggregates_in_two_stages_and_sorts_rows(
    tmp_path: Path,
) -> None:
    benchmark_root = tmp_path / "obb_baseline"
    write_metrics(
        benchmark_root=benchmark_root,
        model_name="oriented_rcnn_r50",
        split_seed=0,
        train_seed=0,
        m_ap50_95=0.50,
        precision=0.80,
        recall=0.50,
    )
    write_metrics(
        benchmark_root=benchmark_root,
        model_name="oriented_rcnn_r50",
        split_seed=0,
        train_seed=1,
        m_ap50_95=0.30,
        precision=0.70,
        recall=0.20,
    )
    write_metrics(
        benchmark_root=benchmark_root,
        model_name="oriented_rcnn_r50",
        split_seed=1,
        train_seed=0,
        m_ap50_95=0.475,
        precision=0.60,
        recall=0.60,
    )
    write_metrics(
        benchmark_root=benchmark_root,
        model_name="yolo11m_obb",
        split_seed=0,
        train_seed=0,
        m_ap50_95=0.42,
        precision=0.50,
        recall=0.50,
    )
    write_metrics(
        benchmark_root=benchmark_root,
        model_name="yolo11m_obb",
        split_seed=0,
        train_seed=1,
        m_ap50_95=0.38,
        precision=0.45,
        recall=0.55,
    )
    write_metrics(
        benchmark_root=benchmark_root,
        model_name="yolo11m_obb",
        split_seed=1,
        train_seed=0,
        m_ap50_95=0.41,
        precision=0.60,
        recall=0.40,
    )

    outputs = collect_suite_outputs(
        benchmark_name="fedo_part2_v1",
        benchmark_root=benchmark_root,
    )

    assert [
        (row["model_name"], row["split_seed"], row["train_seed"])
        for row in outputs.summary_rows
    ] == [
        ("oriented_rcnn_r50", 0, 0),
        ("oriented_rcnn_r50", 0, 1),
        ("oriented_rcnn_r50", 1, 0),
        ("yolo11m_obb", 0, 0),
        ("yolo11m_obb", 0, 1),
        ("yolo11m_obb", 1, 0),
    ]
    assert outputs.summary_rows[0]["f1"] == pytest.approx(2 * 0.8 * 0.5 / (0.8 + 0.5))

    assert [row["model_name"] for row in outputs.leaderboard_rows] == [
        "oriented_rcnn_r50",
        "yolo11m_obb",
    ]
    assert outputs.leaderboard_rows[0]["mAP50_95_mean"] == pytest.approx(0.4375)
    assert outputs.leaderboard_rows[1]["mAP50_95_mean"] == pytest.approx(0.405)


def test_write_suite_outputs_writes_csv_and_markdown_files(tmp_path: Path) -> None:
    benchmark_root = tmp_path / "obb_baseline"
    write_metrics(
        benchmark_root=benchmark_root,
        model_name="oriented_rcnn_r50",
        split_seed=0,
        train_seed=0,
        m_ap50_95=0.50,
        precision=0.80,
        recall=0.50,
    )
    outputs = collect_suite_outputs(
        benchmark_name="fedo_part2_v1",
        benchmark_root=benchmark_root,
    )

    write_suite_outputs(outputs, benchmark_root)

    summary_csv = benchmark_root / "summary.csv"
    leaderboard_csv = benchmark_root / "leaderboard.csv"
    summary_md = benchmark_root / "summary.md"
    assert summary_csv.is_file()
    assert leaderboard_csv.is_file()
    assert summary_md.is_file()

    with summary_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["model_name"] == "oriented_rcnn_r50"

    with leaderboard_csv.open("r", encoding="utf-8", newline="") as handle:
        leaderboard_rows = list(csv.DictReader(handle))
    assert len(leaderboard_rows) == 1
    assert leaderboard_rows[0]["mAP50_95_mean"] == "0.5"


def test_render_summary_markdown_uses_expected_chinese_phrase(tmp_path: Path) -> None:
    benchmark_root = tmp_path / "obb_baseline"
    write_metrics(
        benchmark_root=benchmark_root,
        model_name="oriented_rcnn_r50",
        split_seed=0,
        train_seed=0,
        m_ap50_95=0.50,
        precision=0.80,
        recall=0.50,
    )
    outputs = collect_suite_outputs(
        benchmark_name="fedo_part2_v1",
        benchmark_root=benchmark_root,
    )

    markdown = render_summary_markdown(outputs)
    assert "精度最佳模型" in markdown
    assert "综合最优模型" not in markdown
