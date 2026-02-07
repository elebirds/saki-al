from __future__ import annotations

import hashlib
import uuid
from typing import Any


def to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def normalize_loop_global_config(raw_config: dict[str, Any] | None) -> dict[str, Any]:
    config = dict(raw_config or {})
    job_resources_default = config.get("job_resources_default")
    config["job_resources_default"] = (
        dict(job_resources_default) if isinstance(job_resources_default, dict) else {}
    )
    config["warm_start"] = to_bool(config.get("warm_start"), True)

    selection_raw = config.get("selection")
    selection = dict(selection_raw) if isinstance(selection_raw, dict) else {}
    selection["exclude_open_batches"] = to_bool(selection.get("exclude_open_batches"), True)
    selection["min_candidates_required"] = max(1, to_int(selection.get("min_candidates_required"), 1))
    config["selection"] = selection
    return config


def round_split_seed(loop_id: uuid.UUID, round_index: int) -> int:
    digest = hashlib.sha256(f"{loop_id}:{round_index}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16)
