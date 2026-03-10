#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import csv
import functools
import hashlib
import io
import json
import math
import os
import shutil
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
LATEST_ROUND_QUERY = """
WITH latest_round AS (
  SELECT DISTINCT ON (r.loop_id, r.round_index)
    l.id AS loop_id,
    l.name AS loop_name,
    l.mode::text AS loop_mode,
    l.lifecycle::text AS loop_lifecycle,
    r.id AS round_id,
    r.round_index,
    r.attempt_index,
    r.mode::text AS round_mode,
    r.state::text AS round_state,
    r.plugin_id AS round_plugin_id
  FROM round r
  JOIN loop l ON l.id = r.loop_id
  WHERE l.project_id = %s
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
  lr.round_mode,
  lr.round_state,
  COALESCE(et.plugin_id, tt.plugin_id, lr.round_plugin_id, '') AS plugin_id,
  COALESCE(es.id::text, '') AS eval_step_id,
  COALESCE(et.id::text, '') AS eval_task_id,
  COALESCE(es.state::text, '') AS eval_step_state,
  COALESCE(et.status::text, '') AS eval_task_status,
  COALESCE(es.last_error, '') AS eval_step_last_error,
  COALESCE(et.last_error, '') AS eval_task_last_error,
  COALESCE(es.resolved_params::text, '{}') AS eval_step_resolved_params,
  COALESCE(et.resolved_params::text, '{}') AS eval_task_resolved_params,
  COALESCE(es.metrics::text, '{}') AS eval_metrics,
  COALESCE(ts.id::text, '') AS train_step_id,
  COALESCE(tt.id::text, '') AS train_task_id,
  COALESCE(ts.state::text, '') AS train_step_state,
  COALESCE(tt.status::text, '') AS train_task_status,
  COALESCE(tt.last_error, '') AS train_task_last_error,
  COALESCE(ts.resolved_params::text, '{}') AS train_step_resolved_params,
  COALESCE(tt.resolved_params::text, '{}') AS train_task_resolved_params,
  COALESCE(ts.artifacts::text, '{}') AS train_artifacts,
  COALESCE(ts.metrics::text, '{}') AS train_metrics
FROM latest_round lr
LEFT JOIN step es ON es.round_id = lr.round_id AND es.step_type = 'EVAL'::steptype
LEFT JOIN task et ON et.id = es.task_id
LEFT JOIN step ts ON ts.round_id = lr.round_id AND ts.step_type = 'TRAIN'::steptype
LEFT JOIN task tt ON tt.id = ts.task_id
WHERE
  es.id IS NULL
  OR et.id IS NULL
  OR COALESCE(es.state::text, '') != 'SUCCEEDED'
  OR COALESCE(et.status::text, '') != 'SUCCEEDED'
  OR es.metrics IS NULL
  OR es.metrics = '{}'::jsonb
ORDER BY lr.loop_name, lr.round_index
""".strip()
METRIC_KEYS = ("map50", "map50_95", "precision", "recall")
SELECTED_SIM_GROUPS = (
    "sim-random-yolov8l",
    "sim-uncertainty-yolov8l",
    "sim-aug-rect-yolov8l",
    "sim-aug-obb-yolov8l",
    "sim-aug-boundary-yolov8l",
)
SUMMARY_FIELDS = [
    "loop_name",
    "round_index",
    "attempt_index",
    "round_id",
    "eval_task_id",
    "train_task_id",
    "plugin_id",
    "candidate_reason",
    "original_eval_step_state",
    "original_eval_task_status",
    "original_error",
    "original_map50",
    "original_map50_95",
    "original_precision",
    "original_recall",
    "rerun_status",
    "rerun_message",
    "used_backend",
    "used_device_spec",
    "data_source_kind",
    "data_source_dir",
    "model_source_kind",
    "model_source_ref",
    "rerun_workspace",
    "rerun_report",
    "rerun_events",
    "rerun_map50",
    "rerun_map50_95",
    "rerun_precision",
    "rerun_recall",
    "elapsed_sec",
]
RERUN_METRIC_FIELDS = [
    "loop_name",
    "round_index",
    "attempt_index",
    "eval_task_id",
    "train_task_id",
    "rerun_status",
    "rerun_map50",
    "rerun_map50_95",
    "rerun_precision",
    "rerun_recall",
    "rerun_report",
    "rerun_message",
]
SUPPORTED_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rerun failed latest-attempt YOLO eval tasks by reusing original prepared data "
            "and the train best.pt artifact."
        )
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--database", default="saki")
    parser.add_argument("--password-env", default="PGPASSWORD")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--out-dir", default="runs/exports")
    parser.add_argument("--workspace-root", default="")
    parser.add_argument("--model-cache-dir", default="")
    parser.add_argument("--local-images-dir", default="")
    parser.add_argument("--local-labels-dir", default="")
    parser.add_argument("--fallback-data-dir", default="")
    parser.add_argument("--strict-local-labels", action="store_true")
    parser.add_argument("--selected-sim-groups-only", action="store_true")
    parser.add_argument("--loop-name-regex", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--device-backend", choices=("auto", "cpu", "cuda", "mps"), default="auto")
    parser.add_argument("--device-spec", default="")
    parser.add_argument("--override-batch", type=int, default=0)
    parser.add_argument("--override-imgsz", type=int, default=0)
    parser.add_argument("--env-file", default="")
    parser.add_argument("--s3-endpoint", default="")
    parser.add_argument("--s3-region", default="")
    parser.add_argument("--s3-secure", choices=("auto", "true", "false"), default="auto")
    parser.add_argument("--s3-access-key-env", default="MINIO_ACCESS_KEY")
    parser.add_argument("--s3-secret-key-env", default="MINIO_SECRET_KEY")
    parser.add_argument("--s3-session-token-env", default="AWS_SESSION_TOKEN")
    parser.add_argument("--s3-addressing-style", choices=("auto", "path", "virtual"), default="auto")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def resolve_repo_path(raw: str, *, default: Path) -> Path:
    text = str(raw or "").strip()
    if not text:
        return default.resolve()
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


def parse_bool_text(raw: str, default: bool | None = None) -> bool | None:
    text = str(raw or "").strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def load_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    payload: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        payload[key.strip()] = value.strip().strip("'").strip('"')
    return payload


def text_value(raw: Any) -> str:
    return str(raw or "").strip()


def int_value(raw: Any, default: int = 0) -> int:
    try:
        return int(raw)
    except Exception:
        return default


def parse_json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    text = text_value(raw)
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def metric_number(payload: dict[str, Any], key: str) -> float | None:
    raw = payload.get(key)
    if raw in ("", None):
        return None
    try:
        value = float(raw)
    except Exception:
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def fmt_num(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}"


def is_selected_sim_loop(loop_name: str) -> bool:
    text = text_value(loop_name)
    for prefix in SELECTED_SIM_GROUPS:
        if text == prefix:
            return True
        if text.startswith(prefix + "-") and text[len(prefix) + 1 :].isdigit():
            return True
    return False


@dataclass(frozen=True)
class CandidateRow:
    loop_id: str
    loop_name: str
    loop_mode: str
    loop_lifecycle: str
    round_id: str
    round_index: int
    attempt_index: int
    round_mode: str
    round_state: str
    plugin_id: str
    eval_step_id: str
    eval_task_id: str
    eval_step_state: str
    eval_task_status: str
    eval_step_last_error: str
    eval_task_last_error: str
    eval_step_params: dict[str, Any]
    eval_task_params: dict[str, Any]
    eval_metrics: dict[str, Any]
    train_step_id: str
    train_task_id: str
    train_step_state: str
    train_task_status: str
    train_task_last_error: str
    train_step_params: dict[str, Any]
    train_task_params: dict[str, Any]
    train_artifacts: dict[str, Any]
    train_metrics: dict[str, Any]

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "CandidateRow":
        return cls(
            loop_id=text_value(row.get("loop_id")),
            loop_name=text_value(row.get("loop_name")),
            loop_mode=text_value(row.get("loop_mode")).lower(),
            loop_lifecycle=text_value(row.get("loop_lifecycle")).lower(),
            round_id=text_value(row.get("round_id")),
            round_index=int_value(row.get("round_index")),
            attempt_index=int_value(row.get("attempt_index"), 1),
            round_mode=text_value(row.get("round_mode")).lower(),
            round_state=text_value(row.get("round_state")),
            plugin_id=text_value(row.get("plugin_id")),
            eval_step_id=text_value(row.get("eval_step_id")),
            eval_task_id=text_value(row.get("eval_task_id")),
            eval_step_state=text_value(row.get("eval_step_state")),
            eval_task_status=text_value(row.get("eval_task_status")),
            eval_step_last_error=text_value(row.get("eval_step_last_error")),
            eval_task_last_error=text_value(row.get("eval_task_last_error")),
            eval_step_params=parse_json_object(row.get("eval_step_resolved_params")),
            eval_task_params=parse_json_object(row.get("eval_task_resolved_params")),
            eval_metrics=parse_json_object(row.get("eval_metrics")),
            train_step_id=text_value(row.get("train_step_id")),
            train_task_id=text_value(row.get("train_task_id")),
            train_step_state=text_value(row.get("train_step_state")),
            train_task_status=text_value(row.get("train_task_status")),
            train_task_last_error=text_value(row.get("train_task_last_error")),
            train_step_params=parse_json_object(row.get("train_step_resolved_params")),
            train_task_params=parse_json_object(row.get("train_task_resolved_params")),
            train_artifacts=parse_json_object(row.get("train_artifacts")),
            train_metrics=parse_json_object(row.get("train_metrics")),
        )

    def merged_params(self) -> dict[str, Any]:
        return merged_request_params(self)

    def original_error(self) -> str:
        return self.eval_task_last_error or self.eval_step_last_error

    def original_metric(self, key: str) -> float | None:
        return metric_number(self.eval_metrics, key)

    def has_eval_result(self) -> bool:
        return any(self.original_metric(key) is not None for key in METRIC_KEYS)

    def candidate_reason(self) -> str:
        reasons: list[str] = []
        if not self.eval_step_id:
            reasons.append("missing_eval_step")
        if not self.eval_task_id:
            reasons.append("missing_eval_task")
        if self.eval_step_state != "SUCCEEDED":
            reasons.append(f"eval_step={self.eval_step_state or 'EMPTY'}")
        if self.eval_task_status != "SUCCEEDED":
            reasons.append(f"eval_task={self.eval_task_status or 'EMPTY'}")
        if not self.has_eval_result():
            reasons.append("no_eval_metrics")
        return ",".join(reasons)

    def needs_rerun(self) -> bool:
        return bool(self.candidate_reason())


@dataclass(frozen=True)
class ProjectLabelRow:
    id: str
    name: str
    sort_order: int


@dataclass(frozen=True)
class InputSource:
    kind: str
    local_path: Path | None = None
    ref: str = ""
    message: str = ""


@dataclass(frozen=True)
class StorageConfig:
    endpoint: str
    region: str
    secure: bool | None
    access_key: str
    secret_key: str
    session_token: str
    addressing_style: str

    def endpoint_url(self) -> str | None:
        raw = self.endpoint.strip()
        if not raw:
            return None
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw.rstrip("/")
        secure = self.secure
        if secure is None:
            secure = not (raw.startswith("localhost") or raw.startswith("127.0.0.1") or raw.endswith(":9000"))
        scheme = "https" if secure else "http"
        return f"{scheme}://{raw.rstrip('/')}"


class LocalWorkspace:
    def __init__(self, *, root: Path, task_id: str) -> None:
        self.root = root
        self.task_id = task_id

    @property
    def config_path(self) -> Path:
        return self.root / "config.json"

    @property
    def events_path(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def artifacts_dir(self) -> Path:
        return self.root / "artifacts"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if not self.events_path.exists():
            self.events_path.touch()

    def link_data_dir(self, source_dir: Path) -> None:
        if self.data_dir.exists() or self.data_dir.is_symlink():
            if self.data_dir.is_symlink() or self.data_dir.is_file():
                self.data_dir.unlink()
            else:
                shutil.rmtree(self.data_dir)
        try:
            self.data_dir.symlink_to(source_dir, target_is_directory=True)
        except Exception:
            shutil.copytree(source_dir, self.data_dir)

    def link_model(self, source_path: Path) -> Path:
        target = self.artifacts_dir / "best.pt"
        if target.exists() or target.is_symlink():
            target.unlink()
        try:
            target.symlink_to(source_path)
        except Exception:
            shutil.copy2(source_path, target)
        return target


def add_repo_src_paths() -> None:
    paths = [
        REPO_ROOT / "saki-plugin-sdk/src",
        REPO_ROOT / "saki-plugins/saki-plugin-yolo-det/src",
        REPO_ROOT / "shared/saki-ir/python/src",
    ]
    for path in paths:
        text = str(path)
        if path.exists() and text not in sys.path:
            sys.path.insert(0, text)


@functools.lru_cache(maxsize=1)
def load_eval_runtime() -> tuple[Any, Any, Any, Any, Any]:
    add_repo_src_paths()
    from saki_plugin_sdk import (  # type: ignore
        DeviceBinding,
        ExecutionBindingContext,
        HostCapabilitySnapshot,
        RuntimeCapabilitySnapshot,
        TaskRuntimeContext,
    )
    from saki_plugin_yolo_det.runtime_service import YoloRuntimeService  # type: ignore

    return (
        DeviceBinding,
        ExecutionBindingContext,
        HostCapabilitySnapshot,
        RuntimeCapabilitySnapshot,
        TaskRuntimeContext,
        YoloRuntimeService,
    )


def fetch_rows_via_psycopg(
    *,
    host: str,
    port: int,
    user: str,
    database: str,
    password: str,
    project_id: str,
) -> list[dict[str, Any]]:
    import psycopg  # type: ignore
    from psycopg.rows import dict_row  # type: ignore

    with psycopg.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        dbname=database,
        row_factory=dict_row,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(LATEST_ROUND_QUERY, (project_id,))
            rows = cur.fetchall()
    return [dict(item) for item in rows]


def require_psql() -> str:
    psql = shutil.which("psql")
    if not psql:
        raise RuntimeError("psql not found")
    return psql


def fetch_rows_via_psql(
    *,
    host: str,
    port: int,
    user: str,
    database: str,
    password: str,
    project_id: str,
) -> list[dict[str, str]]:
    escaped = project_id.replace("'", "''")
    query = LATEST_ROUND_QUERY.replace("%s", f"'{escaped}'")
    cmd = [
        require_psql(),
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
    env = dict(os.environ)
    env["PGPASSWORD"] = password
    result = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
    return list(csv.DictReader(io.StringIO(result.stdout)))


def fetch_candidate_rows(
    *,
    host: str,
    port: int,
    user: str,
    database: str,
    password: str,
    project_id: str,
) -> list[CandidateRow]:
    try:
        rows = fetch_rows_via_psycopg(
            host=host,
            port=port,
            user=user,
            database=database,
            password=password,
            project_id=project_id,
        )
    except Exception:
        rows = fetch_rows_via_psql(
            host=host,
            port=port,
            user=user,
            database=database,
            password=password,
            project_id=project_id,
        )
    return [CandidateRow.from_row(row) for row in rows]


def fetch_project_labels(
    *,
    host: str,
    port: int,
    user: str,
    database: str,
    password: str,
    project_id: str,
) -> list[ProjectLabelRow]:
    query = """
SELECT
  id::text AS id,
  name,
  sort_order
FROM label
WHERE project_id = %s
    ORDER BY sort_order ASC, id ASC
""".strip()
    try:
        import psycopg  # type: ignore
        from psycopg.rows import dict_row  # type: ignore

        with psycopg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=database,
            row_factory=dict_row,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (project_id,))
                rows = cur.fetchall()
        rows = [dict(item) for item in rows]
    except Exception:
        escaped = project_id.replace("'", "''")
        psql_query = query.replace("%s", f"'{escaped}'")
        cmd = [
            require_psql(),
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
            f"COPY ({psql_query}) TO STDOUT WITH CSV HEADER",
        ]
        env = dict(os.environ)
        env["PGPASSWORD"] = password
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
        rows = list(csv.DictReader(io.StringIO(result.stdout)))
    return [
        ProjectLabelRow(
            id=text_value(row.get("id")),
            name=text_value(row.get("name")),
            sort_order=int_value(row.get("sort_order"), 0),
        )
        for row in rows
    ]


def fetch_loop_test_partitions(
    *,
    host: str,
    port: int,
    user: str,
    database: str,
    password: str,
    project_id: str,
) -> dict[str, dict[str, list[str]]]:
    query = """
WITH latest_snapshot AS (
  SELECT DISTINCT ON (sv.loop_id)
    sv.loop_id,
    sv.id AS snapshot_version_id
  FROM loop_snapshot_version sv
  JOIN loop l ON l.id = sv.loop_id
  WHERE l.project_id = %s
  ORDER BY sv.loop_id, sv.version_index DESC, sv.created_at DESC, sv.id DESC
)
SELECT
  ls.loop_id::text AS loop_id,
  lower(ss.partition::text) AS partition,
  ss.sample_id::text AS sample_id
FROM latest_snapshot ls
JOIN loop_snapshot_sample ss ON ss.snapshot_version_id = ls.snapshot_version_id
WHERE ss.partition IN ('TEST_ANCHOR', 'TEST_BATCH')
ORDER BY ls.loop_id, partition, ss.sample_id
""".strip()
    try:
        import psycopg  # type: ignore
        from psycopg.rows import dict_row  # type: ignore

        with psycopg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=database,
            row_factory=dict_row,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (project_id,))
                rows = cur.fetchall()
        rows = [dict(item) for item in rows]
    except Exception:
        escaped = project_id.replace("'", "''")
        psql_query = query.replace("%s", f"'{escaped}'")
        cmd = [
            require_psql(),
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
            f"COPY ({psql_query}) TO STDOUT WITH CSV HEADER",
        ]
        env = dict(os.environ)
        env["PGPASSWORD"] = password
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
        rows = list(csv.DictReader(io.StringIO(result.stdout)))

    grouped: dict[str, dict[str, list[str]]] = {}
    for row in rows:
        loop_id = text_value(row.get("loop_id"))
        partition = text_value(row.get("partition")).lower()
        sample_id = text_value(row.get("sample_id"))
        if not loop_id or partition not in {"test_anchor", "test_batch"} or not sample_id:
            continue
        bucket = grouped.setdefault(loop_id, {"test_anchor": [], "test_batch": []})
        bucket[partition].append(sample_id)

    for loop_id, bucket in grouped.items():
        for key in ("test_anchor", "test_batch"):
            bucket[key] = sorted(set(bucket.get(key) or []))
    return grouped


def build_step_root(*, runs_dir: Path, round_id: str, attempt_index: int, task_id: str) -> Path:
    return runs_dir / "rounds" / round_id / f"attempt_{attempt_index}" / "steps" / task_id


def link_or_copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        os.link(src, dst)
    except Exception:
        shutil.copy2(src, dst)


def merged_request_params(candidate: CandidateRow) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for item in (
        candidate.train_task_params,
        candidate.train_step_params,
        candidate.eval_task_params,
        candidate.eval_step_params,
    ):
        payload.update(item)
    return payload


def plugin_params_for_eval(candidate: CandidateRow) -> dict[str, Any]:
    merged = merged_request_params(candidate)
    plugin = merged.get("plugin")
    if isinstance(plugin, dict):
        return dict(plugin)
    return dict(merged)


def include_label_ids_for_candidate(candidate: CandidateRow) -> set[str]:
    merged = merged_request_params(candidate)
    training = merged.get("training")
    training_cfg = training if isinstance(training, dict) else {}
    include_label_ids = training_cfg.get("include_label_ids")
    if not isinstance(include_label_ids, list):
        return set()
    return {
        text_value(item)
        for item in include_label_ids
        if text_value(item)
    }


def ordered_label_rows_for_candidate(
    *,
    candidate: CandidateRow,
    project_labels: list[ProjectLabelRow],
) -> list[ProjectLabelRow]:
    include_label_ids = include_label_ids_for_candidate(candidate)
    if not include_label_ids:
        return list(project_labels)
    return [item for item in project_labels if item.id in include_label_ids]


def find_local_image_path(images_dir: Path, sample_id: str) -> Path:
    exact_matches = [
        path
        for path in images_dir.iterdir()
        if path.is_file() and path.stem == sample_id and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        raise RuntimeError(f"multiple local images found for sample_id={sample_id} under {images_dir}")

    for suffix in SUPPORTED_IMAGE_SUFFIXES:
        candidate = images_dir / f"{sample_id}{suffix}"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"local image not found for sample_id={sample_id} under {images_dir}")


def write_empty_label_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def materialize_local_eval_dataset(
    *,
    candidate: CandidateRow,
    local_images_dir: Path,
    local_labels_dir: Path,
    dataset_cache_root: Path,
    loop_test_partitions: dict[str, dict[str, list[str]]],
    project_labels: list[ProjectLabelRow],
    strict_local_labels: bool,
) -> InputSource:
    partition_rows = loop_test_partitions.get(candidate.loop_id) or {}
    anchor_ids = sorted(set(partition_rows.get("test_anchor") or []))
    batch_ids = sorted(set(partition_rows.get("test_batch") or []))
    composite_ids = sorted(set(anchor_ids).union(batch_ids))
    if not composite_ids:
        return InputSource(
            kind="missing",
            message=f"loop {candidate.loop_name} has no test samples in snapshot partitions",
        )

    label_rows = ordered_label_rows_for_candidate(candidate=candidate, project_labels=project_labels)
    if not label_rows:
        return InputSource(
            kind="missing",
            message=f"loop {candidate.loop_name} resolved zero labels after include_label_ids filtering",
        )

    plugin_params = plugin_params_for_eval(candidate)
    dataset_key_payload = {
        "loop_id": candidate.loop_id,
        "label_ids": [item.id for item in label_rows],
        "images_dir": str(local_images_dir),
        "labels_dir": str(local_labels_dir),
        "anchor_ids": anchor_ids,
        "batch_ids": batch_ids,
        "strict_local_labels": bool(strict_local_labels),
    }
    dataset_key = hashlib.sha256(
        json.dumps(dataset_key_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    dataset_root = dataset_cache_root / dataset_key
    dataset_yaml = dataset_root / "dataset.yaml"
    if dataset_yaml.exists():
        return InputSource(kind="local_yolo_dataset", local_path=dataset_root, ref=str(dataset_root))

    images_val_dir = dataset_root / "images" / "val"
    labels_val_dir = dataset_root / "labels" / "val"
    images_val_dir.mkdir(parents=True, exist_ok=True)
    labels_val_dir.mkdir(parents=True, exist_ok=True)

    missing_labels: list[str] = []
    for sample_id in composite_ids:
        image_path = find_local_image_path(local_images_dir, sample_id)
        image_target = images_val_dir / f"{sample_id}{image_path.suffix.lower()}"
        link_or_copy_file(image_path, image_target)

        label_source = local_labels_dir / f"{sample_id}.txt"
        label_target = labels_val_dir / f"{sample_id}.txt"
        if label_source.exists():
            link_or_copy_file(label_source, label_target)
        else:
            missing_labels.append(sample_id)
            if strict_local_labels:
                raise FileNotFoundError(
                    f"local label not found for sample_id={sample_id} under {local_labels_dir}"
                )
            write_empty_label_file(label_target)

    names = {index: row.name for index, row in enumerate(label_rows)}
    dataset_payload = {
        "path": str(dataset_root.resolve()),
        "train": "images/val",
        "val": "images/val",
        "names": names,
        "val_degraded": False,
        "split_seed": max(0, int_value(merged_request_params(candidate).get("split_seed"), 0)),
    }
    dataset_yaml.write_text(json.dumps(dataset_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    class_schema = {
        "version": 1,
        "classes": [
            {
                "class_index": index,
                "label_id": row.id,
                "class_name": row.name,
                "class_name_norm": " ".join(row.name.strip().lower().split()),
            }
            for index, row in enumerate(label_rows)
        ],
    }
    (dataset_root / "class_schema.json").write_text(
        json.dumps(class_schema, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    dataset_manifest = {
        "sample_count": len(composite_ids),
        "train_sample_count": 0,
        "val_sample_count": len(composite_ids),
        "annotation_count": 0,
        "label_count": len(label_rows),
        "invalid_label_count": 0,
        "skipped_annotation_count": 0,
        "val_degraded": False,
        "split_seed": max(0, int_value(merged_request_params(candidate).get("split_seed"), 0)),
        "val_split_ratio": float(plugin_params.get("val_split_ratio") or 0.2),
        "snapshot_partition_sample_ids": {
            "test_anchor": anchor_ids,
            "test_batch": batch_ids,
        },
        "local_dataset_meta": {
            "images_dir": str(local_images_dir),
            "labels_dir": str(local_labels_dir),
            "strict_local_labels": bool(strict_local_labels),
            "missing_label_count": len(missing_labels),
            "missing_label_sample_ids": missing_labels,
        },
    }
    (dataset_root / "dataset_manifest.json").write_text(
        json.dumps(dataset_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return InputSource(kind="local_yolo_dataset", local_path=dataset_root, ref=str(dataset_root))


def read_dataset_split_seed(dataset_dir: Path) -> int | None:
    path = dataset_dir / "dataset.yaml"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return int_value(payload.get("split_seed"), 0)


def resolve_data_source(
    candidate: CandidateRow,
    *,
    runs_dir: Path,
    fallback_data_dir: Path | None = None,
) -> InputSource:
    if candidate.eval_task_id:
        eval_data_dir = build_step_root(
            runs_dir=runs_dir,
            round_id=candidate.round_id,
            attempt_index=candidate.attempt_index,
            task_id=candidate.eval_task_id,
        ) / "data"
        if (eval_data_dir / "dataset.yaml").exists():
            return InputSource(kind="eval_data", local_path=eval_data_dir, ref=str(eval_data_dir))

    if candidate.train_task_id:
        train_data_dir = build_step_root(
            runs_dir=runs_dir,
            round_id=candidate.round_id,
            attempt_index=candidate.attempt_index,
            task_id=candidate.train_task_id,
        ) / "data"
        if (train_data_dir / "dataset.yaml").exists():
            return InputSource(kind="train_data", local_path=train_data_dir, ref=str(train_data_dir))

    shared_cache_root = runs_dir / "rounds" / candidate.round_id / f"attempt_{candidate.attempt_index}" / "shared" / "data_cache"
    if shared_cache_root.exists():
        dataset_dirs = sorted(
            item
            for item in shared_cache_root.iterdir()
            if item.is_dir() and (item / "dataset.yaml").exists()
        )
        if len(dataset_dirs) == 1:
            return InputSource(kind="shared_cache", local_path=dataset_dirs[0], ref=str(dataset_dirs[0]))
        if len(dataset_dirs) > 1:
            split_seed = int_value(candidate.merged_params().get("split_seed"), 0)
            matched = [item for item in dataset_dirs if read_dataset_split_seed(item) == split_seed]
            if len(matched) == 1:
                return InputSource(kind="shared_cache", local_path=matched[0], ref=str(matched[0]))
            return InputSource(
                kind="missing",
                message=f"multiple shared data caches found under {shared_cache_root}",
            )

    if fallback_data_dir is not None and (fallback_data_dir / "dataset.yaml").exists():
        return InputSource(kind="fallback_data", local_path=fallback_data_dir, ref=str(fallback_data_dir))

    return InputSource(kind="missing", message="dataset.yaml not found in eval/train/shared cache")


def extract_best_pt_uri(artifacts: dict[str, Any]) -> str:
    direct = artifacts.get("best.pt")
    if isinstance(direct, dict):
        uri = text_value(direct.get("uri") or direct.get("storage_uri"))
        if uri:
            return uri

    for key, value in artifacts.items():
        if key == "best.pt":
            continue
        if not isinstance(value, dict):
            continue
        name = text_value(value.get("name"))
        uri = text_value(value.get("uri") or value.get("storage_uri"))
        if name == "best.pt" and uri:
            return uri
        if uri.endswith("/best.pt") or "/best.pt?" in uri:
            return uri
    return ""


def resolve_model_source(candidate: CandidateRow, *, runs_dir: Path) -> InputSource:
    if candidate.eval_task_id:
        eval_best = build_step_root(
            runs_dir=runs_dir,
            round_id=candidate.round_id,
            attempt_index=candidate.attempt_index,
            task_id=candidate.eval_task_id,
        ) / "artifacts" / "best.pt"
        if eval_best.exists():
            return InputSource(kind="eval_best_local", local_path=eval_best, ref=str(eval_best))

    if candidate.train_task_id:
        train_best = build_step_root(
            runs_dir=runs_dir,
            round_id=candidate.round_id,
            attempt_index=candidate.attempt_index,
            task_id=candidate.train_task_id,
        ) / "artifacts" / "best.pt"
        if train_best.exists():
            return InputSource(kind="train_best_local", local_path=train_best, ref=str(train_best))

    shared_best = runs_dir / "rounds" / candidate.round_id / f"attempt_{candidate.attempt_index}" / "shared" / "models" / "best.pt"
    if shared_best.exists():
        return InputSource(kind="shared_best_local", local_path=shared_best, ref=str(shared_best))

    uri = extract_best_pt_uri(candidate.train_artifacts)
    if uri.startswith("s3://"):
        return InputSource(kind="s3_uri", ref=uri)
    if uri.startswith("http://") or uri.startswith("https://"):
        return InputSource(kind="http_uri", ref=uri)
    if uri.startswith("file://"):
        path = Path(urlparse(uri).path)
        if path.exists():
            return InputSource(kind="file_uri", local_path=path, ref=uri)
    if uri:
        path = Path(uri).expanduser()
        if path.exists():
            return InputSource(kind="path", local_path=path, ref=str(path))
    return InputSource(kind="missing", message="best.pt not found locally and no remote artifact uri present")


def build_storage_config(args: argparse.Namespace, env_defaults: dict[str, str]) -> StorageConfig:
    endpoint = text_value(args.s3_endpoint) or text_value(env_defaults.get("MINIO_ENDPOINT"))
    secure = parse_bool_text(args.s3_secure)
    if secure is None:
        secure = parse_bool_text(env_defaults.get("MINIO_SECURE"), None)
    access_key = text_value(os.environ.get(args.s3_access_key_env)) or text_value(env_defaults.get(args.s3_access_key_env))
    secret_key = text_value(os.environ.get(args.s3_secret_key_env)) or text_value(env_defaults.get(args.s3_secret_key_env))
    session_token = text_value(os.environ.get(args.s3_session_token_env)) or text_value(env_defaults.get(args.s3_session_token_env))
    return StorageConfig(
        endpoint=endpoint,
        region=text_value(args.s3_region) or text_value(env_defaults.get("AWS_DEFAULT_REGION")),
        secure=secure,
        access_key=access_key,
        secret_key=secret_key,
        session_token=session_token,
        addressing_style=text_value(args.s3_addressing_style) or "auto",
    )


def parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    bucket = text_value(parsed.netloc)
    key = parsed.path.lstrip("/")
    if not bucket or not key:
        raise ValueError(f"invalid s3 uri: {uri}")
    return bucket, key


def download_via_boto3(*, uri: str, target: Path, storage: StorageConfig) -> None:
    import boto3  # type: ignore
    from botocore.config import Config  # type: ignore

    bucket, key = parse_s3_uri(uri)
    kwargs: dict[str, Any] = {
        "service_name": "s3",
        "endpoint_url": storage.endpoint_url(),
        "aws_access_key_id": storage.access_key or None,
        "aws_secret_access_key": storage.secret_key or None,
        "aws_session_token": storage.session_token or None,
        "region_name": storage.region or None,
        "config": Config(
            signature_version="s3v4",
            s3=(
                {"addressing_style": storage.addressing_style}
                if storage.addressing_style != "auto"
                else {}
            ),
        ),
    }
    client = boto3.client(**kwargs)
    target.parent.mkdir(parents=True, exist_ok=True)
    client.download_file(bucket, key, str(target))


def download_via_aws_cli(*, uri: str, target: Path, storage: StorageConfig) -> None:
    aws = shutil.which("aws")
    if not aws:
        raise RuntimeError("aws cli not found")
    cmd = [aws, "s3", "cp", uri, str(target), "--no-progress"]
    endpoint_url = storage.endpoint_url()
    if endpoint_url:
        cmd.extend(["--endpoint-url", endpoint_url])
    if storage.region:
        cmd.extend(["--region", storage.region])
    env = dict(os.environ)
    if storage.access_key:
        env["AWS_ACCESS_KEY_ID"] = storage.access_key
    if storage.secret_key:
        env["AWS_SECRET_ACCESS_KEY"] = storage.secret_key
    if storage.session_token:
        env["AWS_SESSION_TOKEN"] = storage.session_token
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd, check=True, env=env, capture_output=True, text=True)


def download_http(*, url: str, target: Path) -> None:
    req = Request(url, headers={"User-Agent": "saki-rerun-failed-eval/1.0"})
    target.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(req, timeout=300) as response:
        target.write_bytes(response.read())


def materialize_model_source(
    source: InputSource,
    *,
    model_cache_dir: Path,
    storage: StorageConfig,
) -> tuple[Path, str]:
    if source.local_path and source.local_path.exists():
        return source.local_path, source.kind

    ref = source.ref
    if not ref:
        raise RuntimeError(source.message or "model source is empty")

    suffix = Path(urlparse(ref).path).suffix or ".pt"
    target = model_cache_dir / f"{hashlib.sha256(ref.encode('utf-8')).hexdigest()}{suffix}"
    if target.exists():
        return target, f"{source.kind}_cached"

    if ref.startswith("s3://"):
        try:
            download_via_boto3(uri=ref, target=target, storage=storage)
        except Exception:
            download_via_aws_cli(uri=ref, target=target, storage=storage)
        return target, source.kind

    if ref.startswith("http://") or ref.startswith("https://"):
        download_http(url=ref, target=target)
        return target, source.kind

    if ref.startswith("file://"):
        local_path = Path(urlparse(ref).path)
        if not local_path.exists():
            raise FileNotFoundError(f"model file not found: {local_path}")
        return local_path, source.kind

    local_path = Path(ref).expanduser()
    if not local_path.exists():
        raise FileNotFoundError(f"model file not found: {local_path}")
    return local_path, source.kind


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def dump_events(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def build_rerun_metric_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    metric_rows: list[dict[str, str]] = []
    for row in rows:
        status = text_value(row.get("rerun_status"))
        has_any_metric = any(text_value(row.get(key)) for key in ("rerun_map50", "rerun_map50_95", "rerun_precision", "rerun_recall"))
        if status not in {"RERUN_SUCCEEDED", "RERUN_COMPLETED_NO_METRICS", "SKIPPED_EXISTS"} and not has_any_metric:
            continue
        metric_rows.append({field: text_value(row.get(field)) for field in RERUN_METRIC_FIELDS})
    return metric_rows


def write_optional_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def detect_backend(requested: str, explicit_device_spec: str) -> tuple[str, str, str]:
    backend = requested
    if backend == "auto":
        try:
            import torch  # type: ignore
            if torch.cuda.is_available():
                backend = "cuda"
            elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                backend = "mps"
            else:
                backend = "cpu"
        except Exception:
            backend = "cpu"

    device_spec = text_value(explicit_device_spec)
    if backend == "cuda" and not device_spec:
        device_spec = "0"
    if backend != "cuda":
        device_spec = ""
    profile_id = f"rerun-{backend}{('-' + device_spec) if device_spec else ''}"
    return backend, device_spec, profile_id


def build_execution_context(
    *,
    candidate: CandidateRow,
    backend: str,
    device_spec: str,
    profile_id: str,
) -> Any:
    (
        DeviceBinding,
        ExecutionBindingContext,
        HostCapabilitySnapshot,
        RuntimeCapabilitySnapshot,
        TaskRuntimeContext,
        _YoloRuntimeService,
    ) = load_eval_runtime()

    host_capability = HostCapabilitySnapshot(
        cpu_workers=max(1, os.cpu_count() or 1),
        memory_mb=0,
        gpus=[],
        metal_available=(backend == "mps"),
        platform=sys.platform,
        arch=text_value(os.uname().machine if hasattr(os, "uname") else ""),
        driver_info={},
    )
    runtime_capability = RuntimeCapabilitySnapshot(
        framework="torch",
        framework_version="",
        backends=[backend] if backend else ["cpu"],
        backend_details={},
        errors=[],
    )
    binding = DeviceBinding(
        backend=backend,
        device_spec=device_spec,
        precision="fp32",
        profile_id=profile_id,
        reason="offline_eval_rerun",
        fallback_applied=False,
    )
    task_context = TaskRuntimeContext(
        task_id=candidate.eval_task_id or f"rerun-{candidate.round_id}",
        round_id=candidate.round_id,
        round_index=candidate.round_index,
        attempt=max(1, candidate.attempt_index),
        task_type="eval",
        mode=candidate.round_mode or candidate.loop_mode or "simulation",
        split_seed=max(0, int_value(candidate.merged_params().get("split_seed"), 0)),
        train_seed=max(0, int_value(candidate.merged_params().get("train_seed"), 0)),
        sampling_seed=max(0, int_value(candidate.merged_params().get("sampling_seed"), 0)),
        resolved_device_backend=backend,
    )
    return ExecutionBindingContext(
        task_context=task_context,
        host_capability=host_capability,
        runtime_capability=runtime_capability,
        device_binding=binding,
        profile_id=profile_id,
    )


async def run_eval_once(
    *,
    workspace: LocalWorkspace,
    params: dict[str, Any],
    context: Any,
    verbose: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    (
        _DeviceBinding,
        _ExecutionBindingContext,
        _HostCapabilitySnapshot,
        _RuntimeCapabilitySnapshot,
        _TaskRuntimeContext,
        YoloRuntimeService,
    ) = load_eval_runtime()
    runtime = YoloRuntimeService()
    events: list[dict[str, Any]] = []

    async def emit(topic: str, payload: dict[str, Any]) -> None:
        events.append({"ts": datetime.now(UTC).isoformat(), "topic": topic, "payload": dict(payload or {})})
        if verbose and topic == "log":
            level = text_value(payload.get("level")) or "INFO"
            message = text_value(payload.get("message"))
            print(f"[{level}] {message}")

    output = await runtime.eval(
        workspace=workspace,
        params=params,
        emit=emit,
        context=context,
    )
    return dict(output.metrics or {}), events


def read_report_metrics(report_path: Path) -> dict[str, Any]:
    if not report_path.exists():
        return {}
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    metrics = payload.get("metrics")
    return dict(metrics) if isinstance(metrics, dict) else {}


def build_summary_row(
    *,
    candidate: CandidateRow,
    rerun_status: str,
    rerun_message: str,
    backend: str,
    device_spec: str,
    data_source: InputSource,
    model_source: InputSource,
    workspace_root: Path | None,
    report_path: Path | None,
    events_path: Path | None,
    metrics: dict[str, Any] | None,
    elapsed_sec: float | None,
) -> dict[str, str]:
    rerun_metrics = metrics or {}
    return {
        "loop_name": candidate.loop_name,
        "round_index": str(candidate.round_index),
        "attempt_index": str(candidate.attempt_index),
        "round_id": candidate.round_id,
        "eval_task_id": candidate.eval_task_id,
        "train_task_id": candidate.train_task_id,
        "plugin_id": candidate.plugin_id,
        "candidate_reason": candidate.candidate_reason(),
        "original_eval_step_state": candidate.eval_step_state,
        "original_eval_task_status": candidate.eval_task_status,
        "original_error": candidate.original_error(),
        "original_map50": fmt_num(candidate.original_metric("map50")),
        "original_map50_95": fmt_num(candidate.original_metric("map50_95")),
        "original_precision": fmt_num(candidate.original_metric("precision")),
        "original_recall": fmt_num(candidate.original_metric("recall")),
        "rerun_status": rerun_status,
        "rerun_message": rerun_message,
        "used_backend": backend,
        "used_device_spec": device_spec,
        "data_source_kind": data_source.kind,
        "data_source_dir": str(data_source.local_path) if data_source.local_path else data_source.ref,
        "model_source_kind": model_source.kind,
        "model_source_ref": model_source.ref or (str(model_source.local_path) if model_source.local_path else ""),
        "rerun_workspace": str(workspace_root) if workspace_root else "",
        "rerun_report": str(report_path) if report_path else "",
        "rerun_events": str(events_path) if events_path else "",
        "rerun_map50": fmt_num(metric_number(rerun_metrics, "map50")),
        "rerun_map50_95": fmt_num(metric_number(rerun_metrics, "map50_95")),
        "rerun_precision": fmt_num(metric_number(rerun_metrics, "precision")),
        "rerun_recall": fmt_num(metric_number(rerun_metrics, "recall")),
        "elapsed_sec": "" if elapsed_sec is None else f"{elapsed_sec:.3f}",
    }


def rerun_candidate(
    *,
    candidate: CandidateRow,
    runs_dir: Path,
    workspace_root: Path,
    dataset_cache_root: Path,
    model_cache_dir: Path,
    storage: StorageConfig,
    backend: str,
    device_spec: str,
    profile_id: str,
    project_labels: list[ProjectLabelRow],
    loop_test_partitions: dict[str, dict[str, list[str]]],
    args: argparse.Namespace,
) -> dict[str, str]:
    if args.local_images_dir and args.local_labels_dir:
        local_images_dir = resolve_repo_path(args.local_images_dir, default=Path(args.local_images_dir))
        local_labels_dir = resolve_repo_path(args.local_labels_dir, default=Path(args.local_labels_dir))
        try:
            data_source = materialize_local_eval_dataset(
                candidate=candidate,
                local_images_dir=local_images_dir,
                local_labels_dir=local_labels_dir,
                dataset_cache_root=dataset_cache_root,
                loop_test_partitions=loop_test_partitions,
                project_labels=project_labels,
                strict_local_labels=bool(args.strict_local_labels),
            )
        except Exception as exc:
            data_source = InputSource(kind="missing", message=str(exc))
    else:
        fallback_data_dir = (
            resolve_repo_path(args.fallback_data_dir, default=Path(args.fallback_data_dir))
            if args.fallback_data_dir
            else None
        )
        data_source = resolve_data_source(
            candidate,
            runs_dir=runs_dir,
            fallback_data_dir=fallback_data_dir,
        )
    model_source = resolve_model_source(candidate, runs_dir=runs_dir)

    if args.dry_run:
        return build_summary_row(
            candidate=candidate,
            rerun_status="DRY_RUN",
            rerun_message=data_source.message or model_source.message or "candidate discovered",
            backend=backend,
            device_spec=device_spec,
            data_source=data_source,
            model_source=model_source,
            workspace_root=None,
            report_path=None,
            events_path=None,
            metrics=None,
            elapsed_sec=None,
        )

    if candidate.plugin_id and candidate.plugin_id != "yolo_det_v1":
        return build_summary_row(
            candidate=candidate,
            rerun_status="SKIPPED_UNSUPPORTED_PLUGIN",
            rerun_message=f"only yolo_det_v1 is supported, got {candidate.plugin_id}",
            backend=backend,
            device_spec=device_spec,
            data_source=data_source,
            model_source=model_source,
            workspace_root=None,
            report_path=None,
            events_path=None,
            metrics=None,
            elapsed_sec=None,
        )

    if not candidate.eval_task_id:
        return build_summary_row(
            candidate=candidate,
            rerun_status="SKIPPED_NO_EVAL_TASK",
            rerun_message="eval task id is empty",
            backend=backend,
            device_spec=device_spec,
            data_source=data_source,
            model_source=model_source,
            workspace_root=None,
            report_path=None,
            events_path=None,
            metrics=None,
            elapsed_sec=None,
        )

    if not data_source.local_path or not data_source.local_path.exists():
        return build_summary_row(
            candidate=candidate,
            rerun_status="SKIPPED_NO_DATA",
            rerun_message=data_source.message or "data source missing",
            backend=backend,
            device_spec=device_spec,
            data_source=data_source,
            model_source=model_source,
            workspace_root=None,
            report_path=None,
            events_path=None,
            metrics=None,
            elapsed_sec=None,
        )

    if model_source.kind == "missing":
        return build_summary_row(
            candidate=candidate,
            rerun_status="SKIPPED_NO_MODEL",
            rerun_message=model_source.message or "model source missing",
            backend=backend,
            device_spec=device_spec,
            data_source=data_source,
            model_source=model_source,
            workspace_root=None,
            report_path=None,
            events_path=None,
            metrics=None,
            elapsed_sec=None,
        )

    run_root = workspace_root / candidate.eval_task_id
    report_path = run_root / "artifacts" / "eval_report.json"
    events_path = run_root / "events.jsonl"
    if report_path.exists() and not args.force:
        existing_metrics = read_report_metrics(report_path)
        return build_summary_row(
            candidate=candidate,
            rerun_status="SKIPPED_EXISTS",
            rerun_message="existing rerun report found, use --force to rerun",
            backend=backend,
            device_spec=device_spec,
            data_source=data_source,
            model_source=model_source,
            workspace_root=run_root,
            report_path=report_path,
            events_path=events_path if events_path.exists() else None,
            metrics=existing_metrics,
            elapsed_sec=None,
        )

    try:
        model_path, resolved_model_kind = materialize_model_source(
            model_source,
            model_cache_dir=model_cache_dir,
            storage=storage,
        )
    except Exception as exc:
        return build_summary_row(
            candidate=candidate,
            rerun_status="FAILED_MODEL_PREP",
            rerun_message=str(exc),
            backend=backend,
            device_spec=device_spec,
            data_source=data_source,
            model_source=model_source,
            workspace_root=run_root,
            report_path=None,
            events_path=None,
            metrics=None,
            elapsed_sec=None,
        )

    workspace = LocalWorkspace(root=run_root, task_id=candidate.eval_task_id)
    if run_root.exists() and args.force:
        shutil.rmtree(run_root)
    workspace.ensure()
    workspace.link_data_dir(data_source.local_path)
    workspace.link_model(model_path)

    request_params = merged_request_params(candidate)
    params = plugin_params_for_eval(candidate)
    if args.override_batch > 0:
        params["batch"] = args.override_batch
    if args.override_imgsz > 0:
        params["imgsz"] = args.override_imgsz

    config_snapshot = {
        "project_id": args.project_id,
        "loop_name": candidate.loop_name,
        "round_id": candidate.round_id,
        "round_index": candidate.round_index,
        "attempt_index": candidate.attempt_index,
        "eval_task_id": candidate.eval_task_id,
        "train_task_id": candidate.train_task_id,
        "data_source_kind": data_source.kind,
        "data_source_dir": str(data_source.local_path),
        "model_source_kind": resolved_model_kind,
        "model_source_ref": model_source.ref or str(model_path),
        "backend": backend,
        "device_spec": device_spec,
        "request_params": request_params,
        "plugin_params": params,
    }
    workspace.config_path.write_text(json.dumps(config_snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    start = time.perf_counter()
    try:
        context = build_execution_context(
            candidate=candidate,
            backend=backend,
            device_spec=device_spec,
            profile_id=profile_id,
        )
        metrics, events = asyncio.run(
            run_eval_once(
                workspace=workspace,
                params=params,
                context=context,
                verbose=args.verbose,
            )
        )
        dump_events(workspace.events_path, events)
        elapsed = time.perf_counter() - start
        report_metrics = read_report_metrics(report_path)
        final_metrics = report_metrics or metrics
        if any(metric_number(final_metrics, key) is not None for key in METRIC_KEYS):
            status = "RERUN_SUCCEEDED"
            message = "eval rerun finished"
        else:
            status = "RERUN_COMPLETED_NO_METRICS"
            message = "eval finished but no canonical metrics were produced"
        return build_summary_row(
            candidate=candidate,
            rerun_status=status,
            rerun_message=message,
            backend=backend,
            device_spec=device_spec,
            data_source=data_source,
            model_source=InputSource(kind=resolved_model_kind, local_path=model_path, ref=model_source.ref),
            workspace_root=run_root,
            report_path=report_path if report_path.exists() else None,
            events_path=workspace.events_path if workspace.events_path.exists() else None,
            metrics=final_metrics,
            elapsed_sec=elapsed,
        )
    except Exception as exc:
        elapsed = time.perf_counter() - start
        failure_path = workspace.artifacts_dir / "rerun_failure.txt"
        failure_path.write_text(traceback.format_exc(), encoding="utf-8")
        return build_summary_row(
            candidate=candidate,
            rerun_status="FAILED_RERUN",
            rerun_message=str(exc),
            backend=backend,
            device_spec=device_spec,
            data_source=data_source,
            model_source=InputSource(kind=resolved_model_kind, local_path=model_path, ref=model_source.ref),
            workspace_root=run_root,
            report_path=report_path if report_path.exists() else failure_path,
            events_path=workspace.events_path if workspace.events_path.exists() else None,
            metrics=None,
            elapsed_sec=elapsed,
        )


def main() -> None:
    args = parse_args()
    password = text_value(os.environ.get(args.password_env))
    if not password:
        raise SystemExit(f"{args.password_env} is empty")

    runs_dir = resolve_repo_path(args.runs_dir, default=REPO_ROOT / "runs")
    out_dir = resolve_repo_path(args.out_dir, default=REPO_ROOT / "runs" / "exports")
    env_file: Path | None = None
    if args.env_file:
        env_file = resolve_repo_path(args.env_file, default=REPO_ROOT / ".env")
    elif (REPO_ROOT / ".env").exists():
        env_file = (REPO_ROOT / ".env").resolve()
    env_defaults = load_dotenv(env_file) if env_file is not None else {}
    storage = build_storage_config(args, env_defaults)

    candidate_rows = fetch_candidate_rows(
        host=args.host,
        port=args.port,
        user=args.user,
        database=args.database,
        password=password,
        project_id=args.project_id,
    )
    rerun_candidates = [item for item in candidate_rows if item.needs_rerun()]

    if args.selected_sim_groups_only:
        rerun_candidates = [item for item in rerun_candidates if is_selected_sim_loop(item.loop_name)]

    if args.loop_name_regex:
        import re

        pattern = re.compile(args.loop_name_regex)
        rerun_candidates = [item for item in rerun_candidates if pattern.search(item.loop_name)]

    if args.limit > 0:
        rerun_candidates = rerun_candidates[: args.limit]

    summary_csv = out_dir / f"{args.project_id}_failed_eval_rerun_summary.csv"
    summary_json = out_dir / f"{args.project_id}_failed_eval_rerun_summary.json"
    rerun_metrics_csv = out_dir / f"{args.project_id}_failed_eval_rerun_metrics.csv"
    workspace_root = resolve_repo_path(
        args.workspace_root,
        default=out_dir / f"{args.project_id}_failed_eval_reruns",
    )
    model_cache_dir = resolve_repo_path(
        args.model_cache_dir,
        default=workspace_root / "_model_cache",
    )
    dataset_cache_root = workspace_root / "_datasets"

    backend, device_spec, profile_id = detect_backend(args.device_backend, args.device_spec)
    if rerun_candidates and not args.dry_run:
        try:
            load_eval_runtime()
        except Exception as exc:
            raise SystemExit(f"failed to import YOLO eval runtime: {exc}") from exc

    project_labels: list[ProjectLabelRow] = []
    loop_test_partitions: dict[str, dict[str, list[str]]] = {}
    if args.local_images_dir or args.local_labels_dir:
        if not (args.local_images_dir and args.local_labels_dir):
            raise SystemExit("--local-images-dir 和 --local-labels-dir 必须同时提供")
        project_labels = fetch_project_labels(
            host=args.host,
            port=args.port,
            user=args.user,
            database=args.database,
            password=password,
            project_id=args.project_id,
        )
        loop_test_partitions = fetch_loop_test_partitions(
            host=args.host,
            port=args.port,
            user=args.user,
            database=args.database,
            password=password,
            project_id=args.project_id,
        )

    rows: list[dict[str, str]] = []
    for index, candidate in enumerate(rerun_candidates, start=1):
        print(
            f"[{index}/{len(rerun_candidates)}] {candidate.loop_name} "
            f"round={candidate.round_index} attempt={candidate.attempt_index} eval_task={candidate.eval_task_id}"
        )
        rows.append(
            rerun_candidate(
                candidate=candidate,
                runs_dir=runs_dir,
                workspace_root=workspace_root,
                dataset_cache_root=dataset_cache_root,
                model_cache_dir=model_cache_dir,
                storage=storage,
                backend=backend,
                device_spec=device_spec,
                profile_id=profile_id,
                project_labels=project_labels,
                loop_test_partitions=loop_test_partitions,
                args=args,
            )
        )

    write_csv(summary_csv, rows)
    rerun_metric_rows = build_rerun_metric_rows(rows)
    write_optional_csv(rerun_metrics_csv, rerun_metric_rows, RERUN_METRIC_FIELDS)

    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row["rerun_status"]] = status_counts.get(row["rerun_status"], 0) + 1
    write_json(
        summary_json,
        {
            "generated_at": datetime.now(UTC).isoformat(),
            "project_id": args.project_id,
            "runs_dir": str(runs_dir),
            "workspace_root": str(workspace_root),
            "dataset_cache_root": str(dataset_cache_root),
            "candidate_count": len(rerun_candidates),
            "queried_candidate_row_count": len(candidate_rows),
            "status_counts": status_counts,
            "summary_csv": str(summary_csv),
            "rerun_metrics_csv": str(rerun_metrics_csv),
            "device_backend": backend,
            "device_spec": device_spec,
            "local_images_dir": text_value(args.local_images_dir),
            "local_labels_dir": text_value(args.local_labels_dir),
            "selected_sim_groups_only": bool(args.selected_sim_groups_only),
            "dry_run": bool(args.dry_run),
        },
    )

    print(f"summary_csv={summary_csv}")
    print(f"summary_json={summary_json}")
    print(f"rerun_metrics_csv={rerun_metrics_csv}")
    print(f"candidate_count={len(rerun_candidates)}")
    if status_counts:
        print("status_counts=" + json.dumps(status_counts, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
