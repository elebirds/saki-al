from __future__ import annotations

from typing import Any

from saki_api.core.exceptions import BadRequestAppException


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


def to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def normalize_loop_config(raw_config: dict[str, Any] | None, *, mode: str) -> dict[str, Any]:
    config = dict(raw_config or {})
    plugin = config.get("plugin")
    sampling = config.get("sampling")
    mode_config = config.get("mode")
    reproducibility = config.get("reproducibility")
    execution = config.get("execution")

    normalized_plugin = dict(plugin) if isinstance(plugin, dict) else {}
    normalized_sampling = dict(sampling) if isinstance(sampling, dict) else {}
    normalized_mode = dict(mode_config) if isinstance(mode_config, dict) else {}
    reproducibility_map = dict(reproducibility) if isinstance(reproducibility, dict) else {}
    normalized_repro = {
        "global_seed": str(reproducibility_map.get("global_seed") or "").strip(),
        "deterministic_level": str(reproducibility_map.get("deterministic_level") or "strict").strip(),
    }
    normalized_execution = dict(execution) if isinstance(execution, dict) else {}

    normalized_sampling["strategy"] = str(normalized_sampling.get("strategy") or "").strip()
    normalized_sampling["topk"] = max(1, to_int(normalized_sampling.get("topk"), 200))
    normalized_sampling["unlabeled_page_size"] = max(
        1,
        to_int(normalized_sampling.get("unlabeled_page_size"), 1000),
    )
    normalized_sampling["min_candidates_required"] = max(
        1,
        to_int(normalized_sampling.get("min_candidates_required"), 1),
    )
    normalized_sampling["review_pool_multiplier"] = max(
        1,
        to_int(normalized_sampling.get("review_pool_multiplier"), 3),
    )

    normalized_execution["preferred_accelerator"] = str(
        normalized_execution.get("preferred_accelerator") or "auto"
    ).strip()
    normalized_execution["allow_fallback"] = to_bool(normalized_execution.get("allow_fallback"), True)
    round_resources_default = normalized_execution.get("round_resources_default")
    normalized_execution["round_resources_default"] = (
        dict(round_resources_default) if isinstance(round_resources_default, dict) else {}
    )
    normalized_execution["retry_max_attempts"] = max(
        1,
        to_int(normalized_execution.get("retry_max_attempts"), 3),
    )

    if mode == "manual":
        normalized_mode["confirm_required"] = False
        normalized_sampling = {}
    elif mode == "active_learning":
        normalized_mode["confirm_required"] = to_bool(normalized_mode.get("confirm_required"), True)
    elif mode == "simulation":
        normalized_mode["seed_ratio"] = min(1.0, max(0.0, to_float(normalized_mode.get("seed_ratio"), 0.05)))
        normalized_mode["step_ratio"] = min(1.0, max(0.0, to_float(normalized_mode.get("step_ratio"), 0.05)))
        normalized_mode["random_baseline_enabled"] = to_bool(
            normalized_mode.get("random_baseline_enabled"),
            True,
        )
        seeds_raw = normalized_mode.get("seeds") or [0, 1, 2, 3, 4]
        seeds: list[int] = []
        for item in seeds_raw:
            try:
                seeds.append(int(item))
            except Exception:
                continue
        normalized_mode["seeds"] = seeds or [0, 1, 2, 3, 4]
        normalized_mode.pop("single_seed", None)
    else:
        raise BadRequestAppException(f"unsupported mode: {mode}")

    normalized = {
        "plugin": normalized_plugin,
        "mode": normalized_mode,
        "reproducibility": normalized_repro,
        "execution": normalized_execution,
    }
    if normalized_sampling:
        normalized["sampling"] = normalized_sampling
    validate_loop_config(normalized, mode=mode)
    return normalized


def validate_loop_config(config: dict[str, Any], *, mode: str) -> None:
    sampling = config.get("sampling")
    mode_config = config.get("mode")
    reproducibility = config.get("reproducibility")
    sampling_map = sampling if isinstance(sampling, dict) else {}
    mode_map = mode_config if isinstance(mode_config, dict) else {}
    reproducibility_map = reproducibility if isinstance(reproducibility, dict) else {}
    global_seed = str(reproducibility_map.get("global_seed") or "").strip()
    if not global_seed:
        raise BadRequestAppException("all loop modes require config.reproducibility.global_seed")

    if mode == "manual":
        if sampling_map:
            raise BadRequestAppException("manual mode does not allow config.sampling")
        return

    strategy = str(sampling_map.get("strategy") or "").strip()
    topk = to_int(sampling_map.get("topk"), 0)
    if not strategy:
        raise BadRequestAppException("active_learning/simulation require config.sampling.strategy")
    if topk <= 0:
        raise BadRequestAppException("active_learning/simulation require config.sampling.topk > 0")

    if mode == "simulation":
        oracle_commit_id = str(mode_map.get("oracle_commit_id") or "").strip()
        if not oracle_commit_id:
            raise BadRequestAppException("simulation mode requires config.mode.oracle_commit_id")


def derive_loop_max_rounds(*, mode: str, config: dict[str, Any]) -> int:
    mode_config = config.get("mode")
    mode_map = mode_config if isinstance(mode_config, dict) else {}
    return max(1, to_int(mode_map.get("max_rounds"), 20))


def derive_query_batch_size(*, mode: str, config: dict[str, Any]) -> int:
    if mode == "manual":
        return 1
    sampling = config.get("sampling")
    sampling_map = sampling if isinstance(sampling, dict) else {}
    return max(1, to_int(sampling_map.get("topk"), 200))

def extract_model_request_config(raw_config: dict[str, Any] | None) -> dict[str, Any]:
    config = dict(raw_config or {})
    plugin = config.get("plugin")
    return dict(plugin) if isinstance(plugin, dict) else {}


def merge_model_request_config(
    raw_config: dict[str, Any] | None,
    model_request_config: dict[str, Any] | None,
) -> dict[str, Any]:
    config = dict(raw_config or {})
    config["plugin"] = dict(model_request_config or {})
    return config


def extract_simulation_config(raw_config: dict[str, Any] | None) -> dict[str, Any]:
    config = dict(raw_config or {})
    mode = config.get("mode")
    return dict(mode) if isinstance(mode, dict) else {}


def get_loop_global_seed(raw_config: dict[str, Any] | None) -> str:
    config = dict(raw_config or {})
    reproducibility = config.get("reproducibility")
    reproducibility_map = reproducibility if isinstance(reproducibility, dict) else {}
    return str(reproducibility_map.get("global_seed") or "").strip()
