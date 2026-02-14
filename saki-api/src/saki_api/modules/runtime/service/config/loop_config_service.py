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
    round_resources_default = config.get("round_resources_default")
    config["round_resources_default"] = (
        dict(round_resources_default) if isinstance(round_resources_default, dict) else {}
    )
    config["warm_start"] = to_bool(config.get("warm_start"), True)

    selection_raw = config.get("selection")
    selection = dict(selection_raw) if isinstance(selection_raw, dict) else {}
    selection["min_candidates_required"] = max(1, to_int(selection.get("min_candidates_required"), 1))
    config["selection"] = selection

    simulation = config.get("simulation")
    config["simulation"] = normalize_simulation_config(simulation if isinstance(simulation, dict) else None)
    return config


def extract_model_request_config(raw_config: dict[str, Any] | None) -> dict[str, Any]:
    config = dict(raw_config or {})
    payload = config.get("model_request_config")
    return dict(payload) if isinstance(payload, dict) else {}


def merge_model_request_config(
        raw_config: dict[str, Any] | None,
        model_request_config: dict[str, Any] | None,
) -> dict[str, Any]:
    config = dict(raw_config or {})
    config["model_request_config"] = dict(model_request_config or {})
    return config


def normalize_simulation_config(raw_config: dict[str, Any] | None) -> dict[str, Any]:
    config = dict(raw_config or {})
    oracle_commit_id_raw = str(config.get("oracle_commit_id") or "").strip()
    if oracle_commit_id_raw:
        try:
            oracle_commit_id_raw = str(uuid.UUID(oracle_commit_id_raw))
        except Exception:
            oracle_commit_id_raw = ""

    seed_ratio = float(config.get("seed_ratio", 0.05) or 0.05)
    step_ratio = float(config.get("step_ratio", 0.05) or 0.05)
    seeds_raw = config.get("seeds") or [0, 1, 2, 3, 4]
    seeds: list[int] = []
    for item in seeds_raw:
        try:
            seeds.append(int(item))
        except Exception:
            continue
    if not seeds:
        seeds = [0, 1, 2, 3, 4]

    normalized = {
        "oracle_commit_id": oracle_commit_id_raw,
        "seed_ratio": min(1.0, max(0.0, seed_ratio)),
        "step_ratio": min(1.0, max(0.0, step_ratio)),
        "max_rounds": max(1, to_int(config.get("max_rounds"), 20)),
        "random_baseline_enabled": to_bool(config.get("random_baseline_enabled"), True),
        "seeds": seeds,
    }
    return normalized


def extract_simulation_config(raw_config: dict[str, Any] | None) -> dict[str, Any]:
    config = dict(raw_config or {})
    payload = config.get("simulation")
    if not isinstance(payload, dict):
        return normalize_simulation_config({})
    return normalize_simulation_config(payload)


def merge_simulation_config(
    raw_config: dict[str, Any] | None,
    simulation_config: dict[str, Any] | None,
) -> dict[str, Any]:
    config = dict(raw_config or {})
    config["simulation"] = normalize_simulation_config(simulation_config)
    return config


def build_round_params_from_loop_config(raw_config: dict[str, Any] | None) -> dict[str, Any]:
    """
    轮次执行参数（传给 executor）:
    仅以 `model_request_config` 作为来源。
    其余编排控制参数由 orchestrator 显式注入。
    """
    config = normalize_loop_global_config(raw_config)
    return dict(extract_model_request_config(config))


def round_split_seed(loop_id: uuid.UUID, round_index: int) -> int:
    digest = hashlib.sha256(f"{loop_id}:{round_index}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16)
