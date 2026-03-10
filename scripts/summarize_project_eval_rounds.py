#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import shutil
import statistics
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RoundEvalRow:
    loop_id: str
    loop_name: str
    loop_mode: str
    loop_lifecycle: str
    round_id: str
    round_index: int
    attempt_index: int
    round_state: str
    eval_step_state: str
    eval_task_status: str
    map50: float | None
    map50_95: float | None
    precision: float | None
    recall: float | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize latest-attempt eval metrics by experiment group and round.")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--database", default="saki")
    parser.add_argument("--password-env", default="PGPASSWORD")
    parser.add_argument("--out-dir", default="runs/exports")
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


def parse_float(value: str) -> float | None:
    text = (value or "").strip()
    if not text:
        return None
    return float(text)


def load_latest_round_rows(
    *,
    psql: str,
    env: dict[str, str],
    host: str,
    port: int,
    user: str,
    database: str,
    project_id: str,
) -> list[RoundEvalRow]:
    rows = run_copy(
        psql=psql,
        env=env,
        host=host,
        port=port,
        user=user,
        database=database,
        query=f"""
WITH latest_round AS (
  SELECT DISTINCT ON (r.loop_id, r.round_index)
    l.id AS loop_id,
    l.name AS loop_name,
    l.mode::text AS loop_mode,
    l.lifecycle::text AS loop_lifecycle,
    r.id AS round_id,
    r.round_index,
    r.attempt_index,
    r.state::text AS round_state
  FROM round r
  JOIN loop l ON l.id = r.loop_id
  WHERE l.project_id = '{project_id}'
  ORDER BY r.loop_id, r.round_index, r.attempt_index DESC, r.created_at DESC, r.id DESC
)
SELECT
  lr.loop_id::text AS loop_id,
  lr.loop_name,
  lr.loop_mode,
  lr.loop_lifecycle,
  lr.round_id::text AS round_id,
  lr.round_index,
  lr.attempt_index,
  lr.round_state,
  COALESCE(s.state::text, '') AS eval_step_state,
  COALESCE(t.status::text, '') AS eval_task_status,
  s.metrics->>'map50' AS map50,
  s.metrics->>'map50_95' AS map50_95,
  s.metrics->>'precision' AS precision,
  s.metrics->>'recall' AS recall
FROM latest_round lr
LEFT JOIN step s ON s.round_id = lr.round_id AND s.step_type = 'EVAL'::steptype
LEFT JOIN task t ON t.id = s.task_id
ORDER BY lr.loop_name, lr.round_index
        """.strip(),
    )
    return [
        RoundEvalRow(
            loop_id=row["loop_id"],
            loop_name=row["loop_name"],
            loop_mode=row["loop_mode"],
            loop_lifecycle=row["loop_lifecycle"],
            round_id=row["round_id"],
            round_index=int(row["round_index"]),
            attempt_index=int(row["attempt_index"]),
            round_state=row["round_state"],
            eval_step_state=row["eval_step_state"],
            eval_task_status=row["eval_task_status"],
            map50=parse_float(row["map50"]),
            map50_95=parse_float(row["map50_95"]),
            precision=parse_float(row["precision"]),
            recall=parse_float(row["recall"]),
        )
        for row in rows
    ]


def derive_groups(loop_names: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    suffix_match: dict[str, tuple[str, str]] = {}
    prefix_members: dict[str, list[str]] = defaultdict(list)
    for name in loop_names:
        matched = re.match(r"^(.*)-(\d+)$", name)
        if not matched:
            continue
        prefix, suffix = matched.group(1), matched.group(2)
        suffix_match[name] = (prefix, suffix)
        prefix_members[prefix].append(name)

    group_by_loop: dict[str, str] = {}
    seed_by_loop: dict[str, str] = {}
    for name in loop_names:
        matched = suffix_match.get(name)
        if matched and len(prefix_members[matched[0]]) >= 2:
            group_by_loop[name] = matched[0]
            seed_by_loop[name] = matched[1]
        else:
            group_by_loop[name] = name
            seed_by_loop[name] = ""
    return group_by_loop, seed_by_loop


def is_success(row: RoundEvalRow) -> bool:
    return has_any_result(row)


def has_any_result(row: RoundEvalRow) -> bool:
    return any(
        value is not None
        for value in (row.map50, row.map50_95, row.precision, row.recall)
    )


def is_non_success_status(row: RoundEvalRow) -> bool:
    return row.eval_step_state != "SUCCEEDED" or row.eval_task_status != "SUCCEEDED"


def fmt_num(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}"


def mean(values: list[float | None]) -> float | None:
    cleaned = [value for value in values if value is not None]
    if not cleaned:
        return None
    return sum(cleaned) / len(cleaned)


def std(values: list[float | None]) -> float | None:
    cleaned = [value for value in values if value is not None]
    if len(cleaned) < 2:
        return None
    return statistics.stdev(cleaned)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise SystemExit("没有可写入的统计结果。")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    args = parse_args()
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
    loop_names = sorted({row.loop_name for row in latest_rows})
    group_by_loop, seed_by_loop = derive_groups(loop_names)

    group_members: dict[str, list[str]] = defaultdict(list)
    for loop_name in loop_names:
        group_members[group_by_loop[loop_name]].append(loop_name)
    for members in group_members.values():
        members.sort()

    rows_by_group_round: dict[tuple[str, int], list[RoundEvalRow]] = defaultdict(list)
    for row in latest_rows:
        rows_by_group_round[(group_by_loop[row.loop_name], row.round_index)].append(row)

    stat_rows: list[dict[str, str]] = []
    for (group_name, round_index) in sorted(rows_by_group_round.keys(), key=lambda item: (item[0], item[1])):
        round_rows = sorted(rows_by_group_round[(group_name, round_index)], key=lambda item: item.loop_name)
        success_rows = [row for row in round_rows if is_success(row)]
        failed_rows = [row for row in round_rows if not is_success(row)]
        non_success_included_rows = [row for row in success_rows if is_non_success_status(row)]
        present_loop_names = {row.loop_name for row in round_rows}
        missing_rows = [name for name in group_members[group_name] if name not in present_loop_names]

        notes: list[str] = []
        if non_success_included_rows:
            notes.append(
                "非成功态但已纳入: "
                + "; ".join(
                    f"{row.loop_name}(attempt={row.attempt_index}, eval={row.eval_step_state}/{row.eval_task_status})"
                    for row in non_success_included_rows
                )
            )
        if failed_rows:
            notes.append(
                "排除无结果test: "
                + "; ".join(
                    f"{row.loop_name}(attempt={row.attempt_index}, eval={row.eval_step_state}/{row.eval_task_status})"
                    for row in failed_rows
                )
            )
        if missing_rows:
            notes.append("该round尚未出现: " + ", ".join(missing_rows))

        stat_rows.append(
            {
                "experiment_group": group_name,
                "group_kind": "seeded" if any(seed_by_loop[name] for name in group_members[group_name]) else "single",
                "member_loop_count": str(len(group_members[group_name])),
                "member_loops": "; ".join(group_members[group_name]),
                "round_index": str(round_index),
                "included_result_count": str(len(success_rows)),
                "included_non_success_with_result_count": str(len(non_success_included_rows)),
                "excluded_no_result_count": str(len(failed_rows)),
                "missing_loop_count": str(len(missing_rows)),
                "map50_avg": fmt_num(mean([row.map50 for row in success_rows])),
                "map50_std": fmt_num(std([row.map50 for row in success_rows])),
                "map50_95_avg": fmt_num(mean([row.map50_95 for row in success_rows])),
                "map50_95_std": fmt_num(std([row.map50_95 for row in success_rows])),
                "precision_avg": fmt_num(mean([row.precision for row in success_rows])),
                "precision_std": fmt_num(std([row.precision for row in success_rows])),
                "recall_avg": fmt_num(mean([row.recall for row in success_rows])),
                "recall_std": fmt_num(std([row.recall for row in success_rows])),
                "notes": " | ".join(notes),
            }
        )

    group_rounds: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in stat_rows:
        group_rounds[row["experiment_group"]].append(row)

    seeded_groups = sorted(
        [name for name, members in group_members.items() if any(seed_by_loop[loop_name] for loop_name in members)]
    )
    single_groups = sorted(
        [name for name, members in group_members.items() if not any(seed_by_loop[loop_name] for loop_name in members)]
    )

    overview_lines = [
        f"# Project {args.project_id} 实验汇总",
        "",
        "口径：每个 loop 的每个 round 只取最后一次 attempt；统计指标取该 round 的 EVAL 结果（map50 / map50_95 / precision / recall）；同一实验组某个 round 只要任一 seed 有结果，该 round 就保留；avg/std 仅按有结果的 seed 计算，不要求 EVAL 成功态；只有全部 seed 都无结果时，该 round 才视为无结果。",
        "",
        f"- 共识别出 {len(group_members)} 个实验组。",
        f"- 其中多 seed 实验组 {len(seeded_groups)} 个，单独实验 {len(single_groups)} 个。",
        "",
        "## 多 Seed 实验组",
    ]
    for group_name in seeded_groups:
        overview_lines.append(f"- `{group_name}`: {', '.join(group_members[group_name])}")
    overview_lines.extend(["", "## 单独实验"])
    for group_name in single_groups:
        overview_lines.append(f"- `{group_name}`")

    out_dir = Path(args.out_dir)
    csv_path = out_dir / f"{args.project_id}_experiment_round_eval_stats.csv"
    md_path = out_dir / f"{args.project_id}_experiment_overview.md"
    write_csv(csv_path, stat_rows)
    write_markdown(md_path, "\n".join(overview_lines) + "\n")
    print(csv_path)
    print(md_path)


if __name__ == "__main__":
    main()
