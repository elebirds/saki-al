#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path


SELECTED_GROUPS = [
    "sim-random-yolov8l",
    "sim-uncertainty-yolov8l",
    "sim-aug-rect-yolov8l",
    "sim-aug-obb-yolov8l",
    "sim-aug-boundary-yolov8l",
]

DISPLAY_NAME = {
    "sim-random-yolov8l": "Random",
    "sim-uncertainty-yolov8l": "Uncertainty",
    "sim-aug-rect-yolov8l": "Aug-Rect",
    "sim-aug-obb-yolov8l": "Aug-OBB",
    "sim-aug-boundary-yolov8l": "Aug-Boundary",
}


@dataclass(frozen=True)
class StatRow:
    experiment_group: str
    round_index: int
    included_result_count: int
    excluded_no_result_count: int
    map50_avg: float | None
    map50_std: float | None
    map50_95_avg: float | None
    map50_95_std: float | None
    precision_avg: float | None
    precision_std: float | None
    recall_avg: float | None
    recall_std: float | None
    notes: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate paper-ready strategy comparison tables from aggregated eval stats.")
    parser.add_argument("--stats-csv", required=True)
    parser.add_argument("--output-md", required=True)
    parser.add_argument("--output-tex", required=True)
    return parser.parse_args()


def parse_float(value: str) -> float | None:
    text = (value or "").strip()
    if not text:
        return None
    return float(text)


def load_rows(path: Path) -> dict[str, list[StatRow]]:
    rows_by_group: dict[str, list[StatRow]] = {group: [] for group in SELECTED_GROUPS}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            group = (row.get("experiment_group") or "").strip()
            if group not in rows_by_group:
                continue
            rows_by_group[group].append(
                StatRow(
                    experiment_group=group,
                    round_index=int((row.get("round_index") or "0").strip() or 0),
                    included_result_count=int((row.get("included_result_count") or "0").strip() or 0),
                    excluded_no_result_count=int((row.get("excluded_no_result_count") or "0").strip() or 0),
                    map50_avg=parse_float(row.get("map50_avg") or ""),
                    map50_std=parse_float(row.get("map50_std") or ""),
                    map50_95_avg=parse_float(row.get("map50_95_avg") or ""),
                    map50_95_std=parse_float(row.get("map50_95_std") or ""),
                    precision_avg=parse_float(row.get("precision_avg") or ""),
                    precision_std=parse_float(row.get("precision_std") or ""),
                    recall_avg=parse_float(row.get("recall_avg") or ""),
                    recall_std=parse_float(row.get("recall_std") or ""),
                    notes=(row.get("notes") or "").strip(),
                )
            )
    for group, rows in rows_by_group.items():
        if not rows:
            raise SystemExit(f"统计 CSV 缺少实验组: {group}")
        rows.sort(key=lambda item: item.round_index)
    return rows_by_group


def mean(values: list[float | None]) -> float | None:
    cleaned = [value for value in values if value is not None]
    if not cleaned:
        return None
    return sum(cleaned) / len(cleaned)


def f1_score(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    if precision + recall <= 0:
        return None
    return 2.0 * precision * recall / (precision + recall)


def first_ge(rows: list[StatRow], key: str, threshold: float) -> int | None:
    for row in rows:
        value = getattr(row, key)
        if value is not None and value >= threshold:
            return row.round_index
    return None


def best_row(rows: list[StatRow]) -> StatRow:
    return max(rows, key=lambda item: item.map50_95_avg if item.map50_95_avg is not None else -1.0)


def fmt(value: float | None, digits: int = 4) -> str:
    if value is None:
        return "--"
    return f"{value:.{digits}f}"


def fmt_pm(avg: float | None, std: float | None, digits: int = 4) -> str:
    if avg is None:
        return "--"
    if std is None:
        return f"{avg:.{digits}f}"
    return f"{avg:.{digits}f} ± {std:.{digits}f}"


def latex_escape(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    out = text
    for src, dst in replacements.items():
        out = out.replace(src, dst)
    return out


def build_final_rows(rows_by_group: dict[str, list[StatRow]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    ranking = sorted(
        SELECTED_GROUPS,
        key=lambda group: rows_by_group[group][-1].map50_95_avg if rows_by_group[group][-1].map50_95_avg is not None else -1.0,
        reverse=True,
    )
    rank_map = {group: index + 1 for index, group in enumerate(ranking)}
    for group in ranking:
        row = rows_by_group[group][-1]
        rows.append(
            {
                "strategy": DISPLAY_NAME[group],
                "final_round": str(row.round_index),
                "map50_95": fmt_pm(row.map50_95_avg, row.map50_95_std),
                "map50": fmt_pm(row.map50_avg, row.map50_std),
                "precision": fmt_pm(row.precision_avg, row.precision_std),
                "recall": fmt_pm(row.recall_avg, row.recall_std),
                "f1": fmt(f1_score(row.precision_avg, row.recall_avg)),
                "rank": str(rank_map[group]),
            }
        )
    return rows


def build_process_rows(rows_by_group: dict[str, list[StatRow]]) -> list[dict[str, str]]:
    ranking = sorted(
        SELECTED_GROUPS,
        key=lambda group: mean([row.map50_95_avg for row in rows_by_group[group]]) or -1.0,
        reverse=True,
    )
    rows: list[dict[str, str]] = []
    for group in ranking:
        rows_for_group = rows_by_group[group]
        rows.append(
            {
                "strategy": DISPLAY_NAME[group],
                "mean_map50_95": fmt(mean([row.map50_95_avg for row in rows_for_group])),
                "mean_map50": fmt(mean([row.map50_avg for row in rows_for_group])),
                "auc_map50_95": fmt(sum(row.map50_95_avg or 0.0 for row in rows_for_group)),
                "auc_map50": fmt(sum(row.map50_avg or 0.0 for row in rows_for_group)),
                "mean_std95": fmt(mean([row.map50_95_std for row in rows_for_group])),
                "mean_std50": fmt(mean([row.map50_std for row in rows_for_group])),
            }
        )
    return rows


def build_convergence_rows(rows_by_group: dict[str, list[StatRow]]) -> list[dict[str, str]]:
    ranking = sorted(
        SELECTED_GROUPS,
        key=lambda group: (
            first_ge(rows_by_group[group], "map50_95_avg", 0.40) is None,
            first_ge(rows_by_group[group], "map50_95_avg", 0.40) or 10**9,
            -(best_row(rows_by_group[group]).map50_95_avg or 0.0),
        ),
    )
    rows: list[dict[str, str]] = []
    for group in ranking:
        best = best_row(rows_by_group[group])
        rows.append(
            {
                "strategy": DISPLAY_NAME[group],
                "first_038": str(first_ge(rows_by_group[group], "map50_95_avg", 0.38) or "--"),
                "first_040": str(first_ge(rows_by_group[group], "map50_95_avg", 0.40) or "--"),
                "peak_round": str(best.round_index),
                "peak_map50_95": fmt(best.map50_95_avg),
                "peak_map50": fmt(best.map50_avg),
                "peak_f1": fmt(f1_score(best.precision_avg, best.recall_avg)),
            }
        )
    return rows


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def latex_table(
    *,
    caption: str,
    label: str,
    headers: list[str],
    rows: list[list[str]],
    column_spec: str,
    note: str,
) -> str:
    body_lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        rf"\caption{{{latex_escape(caption)}}}",
        rf"\label{{{latex_escape(label)}}}",
        r"\small",
        rf"\begin{{tabular}}{{{column_spec}}}",
        r"\toprule",
        " & ".join(latex_escape(item) for item in headers) + r" \\",
        r"\midrule",
    ]
    for row in rows:
        body_lines.append(" & ".join(latex_escape(item) for item in row) + r" \\")
    body_lines.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            r"\par\smallskip",
            r"{\footnotesize " + latex_escape(note) + r"}",
            r"\end{table}",
        ]
    )
    return "\n".join(body_lines)


def main() -> None:
    args = parse_args()
    rows_by_group = load_rows(Path(args.stats_csv))

    final_rows = build_final_rows(rows_by_group)
    process_rows = build_process_rows(rows_by_group)
    convergence_rows = build_convergence_rows(rows_by_group)

    final_headers = ["策略", "最终轮次", "mAP50_95", "mAP50", "Precision", "Recall", "F1", "排名"]
    final_body = [
        [row["strategy"], row["final_round"], row["map50_95"], row["map50"], row["precision"], row["recall"], row["f1"], row["rank"]]
        for row in final_rows
    ]
    process_headers = ["策略", "全程均值 mAP50_95", "全程均值 mAP50", "AUC(mAP50_95)", "AUC(mAP50)", "平均 std95", "平均 std50"]
    process_body = [
        [row["strategy"], row["mean_map50_95"], row["mean_map50"], row["auc_map50_95"], row["auc_map50"], row["mean_std95"], row["mean_std50"]]
        for row in process_rows
    ]
    convergence_headers = ["策略", "首次≥0.38 轮次", "首次≥0.40 轮次", "峰值轮次", "峰值 mAP50_95", "峰值 mAP50", "峰值 F1"]
    convergence_body = [
        [row["strategy"], row["first_038"], row["first_040"], row["peak_round"], row["peak_map50_95"], row["peak_map50"], row["peak_f1"]]
        for row in convergence_rows
    ]

    md_lines = [
        "# 论文表格（可直接粘贴）",
        "",
        "## 表 1 最终性能对比",
        markdown_table(final_headers, final_body),
        "",
        "注：`mAP50_95`、`mAP50`、`Precision`、`Recall` 为最终 round 的 `avg ± std`。`F1 = 2PR / (P + R)`，按表中聚合后的 Precision 与 Recall 计算。",
        "",
        "## 表 2 过程表现对比",
        markdown_table(process_headers, process_body),
        "",
        "注：AUC 为 20 轮 `mAP` 曲线的离散累加值，用于衡量整个主动学习过程的累计收益；平均 std 越小表示不同 seed 之间越稳定。",
        "",
        "## 表 3 收敛与峰值表现",
        markdown_table(convergence_headers, convergence_body),
        "",
        "注：阈值轮次表示首次达到对应 `mAP50_95` 水平的 round；峰值轮次按 `mAP50_95` 最大时刻确定。",
        "",
    ]
    Path(args.output_md).write_text("\n".join(md_lines), encoding="utf-8")

    tex_lines = [
        "% Requires: \\usepackage{booktabs}",
        "",
        latex_table(
            caption="五种主动学习策略的最终性能对比（补跑结果已合并）",
            label="tab:al-final-performance",
            headers=final_headers,
            rows=final_body,
            column_spec="lccccccc",
            note="mAP50_95、mAP50、Precision、Recall 为最终 round 的 avg ± std。F1 按聚合后的 Precision 与 Recall 计算。",
        ),
        "",
        latex_table(
            caption="五种主动学习策略的过程表现对比",
            label="tab:al-process-performance",
            headers=process_headers,
            rows=process_body,
            column_spec="lcccccc",
            note="AUC 为 20 轮 mAP 曲线的离散累加值，用于衡量整个主动学习过程的累计收益；平均 std 越小表示不同 seed 之间越稳定。",
        ),
        "",
        latex_table(
            caption="五种主动学习策略的收敛与峰值表现",
            label="tab:al-convergence-peak",
            headers=convergence_headers,
            rows=convergence_body,
            column_spec="lcccccc",
            note="阈值轮次表示首次达到对应 mAP50_95 水平的 round；峰值轮次按 mAP50_95 最大时刻确定。",
        ),
        "",
    ]
    Path(args.output_tex).write_text("\n".join(tex_lines), encoding="utf-8")

    print(args.output_md)
    print(args.output_tex)


if __name__ == "__main__":
    main()
