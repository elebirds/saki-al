#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict
from pathlib import Path

from summarize_project_eval_rounds import (
    derive_groups,
    fmt_num,
    load_latest_round_rows,
    load_rerun_metric_rows,
    overlay_rerun_metrics,
    require_psql,
)


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate appendix tables for the thesis from final eval statistics.")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--database", default="saki")
    parser.add_argument("--password-env", default="PGPASSWORD")
    parser.add_argument("--stats-csv", required=True)
    parser.add_argument("--rerun-metrics-csv", required=True)
    parser.add_argument("--output-md", required=True)
    parser.add_argument("--output-tex", required=True)
    return parser.parse_args()


def parse_float(value: str) -> float | None:
    text = (value or "").strip()
    if not text:
        return None
    return float(text)


def f1_score(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    if precision + recall <= 0:
        return None
    return 2.0 * precision * recall / (precision + recall)


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


def load_round_summary_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [row for row in rows if (row.get("experiment_group") or "").strip() in SELECTED_GROUPS]


def build_appendix_round_rows(path: Path) -> list[list[str]]:
    rows = load_round_summary_rows(path)
    rows.sort(key=lambda row: (SELECTED_GROUPS.index(row["experiment_group"]), int(row["round_index"])))
    output: list[list[str]] = []
    for row in rows:
        precision = parse_float(row["precision_avg"])
        recall = parse_float(row["recall_avg"])
        output.append(
            [
                DISPLAY_NAME[row["experiment_group"]],
                row["round_index"],
                row["included_result_count"],
                fmt_num(parse_float(row["map50_95_avg"])) or "--",
                fmt_num(parse_float(row["map50_95_std"])) or "--",
                fmt_num(parse_float(row["map50_avg"])) or "--",
                fmt_num(parse_float(row["map50_std"])) or "--",
                fmt_num(precision) or "--",
                fmt_num(recall) or "--",
                fmt_num(f1_score(precision, recall)) or "--",
            ]
        )
    return output


def load_final_seed_rows(args: argparse.Namespace) -> list[list[str]]:
    password = os.environ.get(args.password_env, "")
    if not password:
        raise SystemExit(f"环境变量 {args.password_env} 为空，无法连接数据库。")

    psql = require_psql()
    env = dict(os.environ)
    env["PGPASSWORD"] = password
    latest_rows = load_latest_round_rows(
        psql=psql,
        env=env,
        host=args.host,
        port=args.port,
        user=args.user,
        database=args.database,
        project_id=args.project_id,
    )
    rerun_overrides = load_rerun_metric_rows(Path(args.rerun_metrics_csv))
    latest_rows, _applied = overlay_rerun_metrics(latest_rows, rerun_overrides)

    loop_names = sorted({row.loop_name for row in latest_rows})
    group_by_loop, seed_by_loop = derive_groups(loop_names)
    selected_loops = [
        loop_name
        for loop_name in loop_names
        if group_by_loop.get(loop_name) in SELECTED_GROUPS
    ]

    rows_by_loop: dict[str, list] = defaultdict(list)
    for row in latest_rows:
        if row.loop_name in selected_loops:
            rows_by_loop[row.loop_name].append(row)

    output: list[list[str]] = []
    for loop_name in sorted(
        selected_loops,
        key=lambda name: (SELECTED_GROUPS.index(group_by_loop[name]), int(seed_by_loop[name] or 0), name),
    ):
        final_row = max(rows_by_loop[loop_name], key=lambda row: (row.round_index, row.attempt_index))
        precision = final_row.precision
        recall = final_row.recall
        output.append(
            [
                DISPLAY_NAME[group_by_loop[loop_name]],
                seed_by_loop[loop_name] or "--",
                loop_name,
                str(final_row.round_index),
                fmt_num(final_row.map50_95) or "--",
                fmt_num(final_row.map50) or "--",
                fmt_num(precision) or "--",
                fmt_num(recall) or "--",
                fmt_num(f1_score(precision, recall)) or "--",
                final_row.metric_source,
            ]
        )
    return output


def build_rerun_summary_rows(path: Path, stats_path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rerun_rows = list(csv.DictReader(handle))
    rerun_rows = [row for row in rerun_rows if (row.get("loop_name") or "").strip()]

    stats_rows = load_round_summary_rows(stats_path)
    excluded_by_group: dict[str, int] = defaultdict(int)
    repaired_group_rounds: dict[str, set[str]] = defaultdict(set)
    for row in stats_rows:
        group = row["experiment_group"]
        excluded_by_group[group] += int((row.get("excluded_no_result_count") or "0").strip() or 0)
        notes = row.get("notes") or ""
        if "补跑覆盖:" in notes:
            repaired_group_rounds[group].add(row["round_index"])

    failed_count: dict[str, int] = defaultdict(int)
    success_count: dict[str, int] = defaultdict(int)
    repaired_loop_rounds: dict[str, list[str]] = defaultdict(list)
    for row in rerun_rows:
        loop_name = (row.get("loop_name") or "").strip()
        matched = None
        for group in SELECTED_GROUPS:
            if loop_name == group or loop_name.startswith(group + "-"):
                matched = group
                break
        if matched is None:
            continue
        failed_count[matched] += 1
        if (row.get("rerun_status") or "").strip() == "RERUN_SUCCEEDED":
            success_count[matched] += 1
            repaired_loop_rounds[matched].append(f"{loop_name}:r{row['round_index']}")

    output: list[list[str]] = []
    for group in SELECTED_GROUPS:
        output.append(
            [
                DISPLAY_NAME[group],
                str(failed_count[group]),
                str(success_count[group]),
                str(len(repaired_group_rounds[group])),
                str(excluded_by_group[group]),
                ", ".join(sorted(repaired_group_rounds[group], key=lambda x: int(x))) or "--",
            ]
        )
    return output


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def latex_longtable(
    *,
    caption: str,
    label: str,
    headers: list[str],
    rows: list[list[str]],
    column_spec: str,
    note: str,
) -> str:
    body = [
        rf"\begin{{longtable}}{{{column_spec}}}",
        rf"\caption{{{latex_escape(caption)}}}\label{{{latex_escape(label)}}}\\",
        r"\toprule",
        " & ".join(latex_escape(item) for item in headers) + r" \\",
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        " & ".join(latex_escape(item) for item in headers) + r" \\",
        r"\midrule",
        r"\endhead",
        r"\bottomrule",
        r"\multicolumn{" + str(len(headers)) + r"}{p{0.92\linewidth}}{\footnotesize " + latex_escape(note) + r"} \\",
        r"\endfoot",
    ]
    for row in rows:
        body.append(" & ".join(latex_escape(item) for item in row) + r" \\")
    body.append(r"\end{longtable}")
    return "\n".join(body)


def latex_table(
    *,
    caption: str,
    label: str,
    headers: list[str],
    rows: list[list[str]],
    column_spec: str,
    note: str,
) -> str:
    body = [
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
        body.append(" & ".join(latex_escape(item) for item in row) + r" \\")
    body.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            r"\par\smallskip",
            r"{\footnotesize " + latex_escape(note) + r"}",
            r"\end{table}",
        ]
    )
    return "\n".join(body)


def main() -> None:
    args = parse_args()
    stats_path = Path(args.stats_csv)
    rerun_path = Path(args.rerun_metrics_csv)

    appendix_round_rows = build_appendix_round_rows(stats_path)
    appendix_seed_rows = load_final_seed_rows(args)
    appendix_rerun_rows = build_rerun_summary_rows(rerun_path, stats_path)

    headers_a1 = ["策略", "Round", "纳入Seed数", "mAP50_95均值", "mAP50_95标准差", "mAP50均值", "mAP50标准差", "Precision", "Recall", "F1"]
    headers_a2 = ["策略", "Seed", "Loop", "最终轮次", "mAP50_95", "mAP50", "Precision", "Recall", "F1", "来源"]
    headers_a3 = ["策略", "原失败Eval数", "补跑成功数", "覆盖统计Round数", "合并后排除数", "修复Round"]

    md_lines = [
        "# 附录表格（可直接粘贴）",
        "",
        "## 表 A1 五种策略逐轮汇总结果",
        markdown_table(headers_a1, appendix_round_rows),
        "",
        "注：本表基于合并补跑结果后的最终统计 CSV，按 experiment group 和 round 聚合；F1 按聚合后的 Precision 与 Recall 计算。",
        "",
        "## 表 A2 各 Seed 的最终轮结果",
        markdown_table(headers_a2, appendix_seed_rows),
        "",
        "注：来源列中 `db` 表示直接来自数据库中的最终 EVAL 结果，`rerun:*` 表示该 round 的指标由离线补跑覆盖。",
        "",
        "## 表 A3 失败 Eval 补跑修复汇总",
        markdown_table(headers_a3, appendix_rerun_rows),
        "",
        "注：覆盖统计 Round 数按实验组聚合后统计；合并后排除数来自最终统计 CSV 的 `excluded_no_result_count` 总和。",
        "",
    ]
    Path(args.output_md).write_text("\n".join(md_lines), encoding="utf-8")

    tex_lines = [
        "% Requires: \\usepackage{booktabs}",
        "% Requires: \\usepackage{longtable}",
        "",
        latex_longtable(
            caption="五种主动学习策略逐轮汇总结果",
            label="tab:appendix-round-results",
            headers=headers_a1,
            rows=appendix_round_rows,
            column_spec="lccccccccc",
            note="本表基于合并补跑结果后的最终统计 CSV，按 experiment group 和 round 聚合；F1 按聚合后的 Precision 与 Recall 计算。",
        ),
        "",
        latex_longtable(
            caption="各 Seed 的最终轮结果",
            label="tab:appendix-seed-final-results",
            headers=headers_a2,
            rows=appendix_seed_rows,
            column_spec="lcclcccccl",
            note="来源列中 db 表示直接来自数据库中的最终 EVAL 结果，rerun:* 表示该 round 的指标由离线补跑覆盖。",
        ),
        "",
        latex_table(
            caption="失败 Eval 补跑修复汇总",
            label="tab:appendix-rerun-summary",
            headers=headers_a3,
            rows=appendix_rerun_rows,
            column_spec="lccccc",
            note="覆盖统计 Round 数按实验组聚合后统计；合并后排除数来自最终统计 CSV 的 excluded_no_result_count 总和。",
        ),
        "",
    ]
    Path(args.output_tex).write_text("\n".join(tex_lines), encoding="utf-8")

    print(args.output_md)
    print(args.output_tex)


if __name__ == "__main__":
    main()
