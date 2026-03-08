from __future__ import annotations

import math
import uuid
from typing import Any

from saki_api.core.exceptions import BadRequestAppException
from saki_api.modules.shared.modeling.enums import SnapshotValPolicy

_DETERMINISTIC_LEVEL_OFF = "off"
_DETERMINISTIC_LEVEL_DETERMINISTIC = "deterministic"
_DETERMINISTIC_LEVEL_STRONG = "strong_deterministic"
_ALLOWED_DETERMINISTIC_LEVELS: tuple[str, ...] = (
    _DETERMINISTIC_LEVEL_OFF,
    _DETERMINISTIC_LEVEL_DETERMINISTIC,
    _DETERMINISTIC_LEVEL_STRONG,
)


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


def _normalize_deterministic_level(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return _DETERMINISTIC_LEVEL_OFF
    if text in _ALLOWED_DETERMINISTIC_LEVELS:
        return text
    raise BadRequestAppException(
        "invalid config.reproducibility.deterministic_level: "
        f"{value}. allowed={list(_ALLOWED_DETERMINISTIC_LEVELS)}"
    )


def _normalize_non_negative_seed(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise BadRequestAppException(
            f"invalid config.reproducibility.{field_name}: {value}. must be an integer >= 0"
        )
    if isinstance(value, int):
        seed = value
    elif isinstance(value, float):
        if (not math.isfinite(value)) or (not value.is_integer()):
            raise BadRequestAppException(
                f"invalid config.reproducibility.{field_name}: {value}. must be an integer >= 0"
            )
        seed = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise BadRequestAppException(
                f"invalid config.reproducibility.{field_name}: {value}. must be an integer >= 0"
            )
        try:
            seed = int(text)
        except Exception as exc:
            raise BadRequestAppException(
                f"invalid config.reproducibility.{field_name}: {value}. must be an integer >= 0"
            ) from exc
    else:
        try:
            seed = int(value)
        except Exception as exc:
            raise BadRequestAppException(
                f"invalid config.reproducibility.{field_name}: {value}. must be an integer >= 0"
            ) from exc

    if seed < 0:
        raise BadRequestAppException(
            f"invalid config.reproducibility.{field_name}: {value}. must be an integer >= 0"
        )
    return seed


def _normalize_snapshot_val_policy(value: Any) -> str:
    if isinstance(value, SnapshotValPolicy):
        return str(value.value)
    text = str(value or "").strip()
    if not text:
        return SnapshotValPolicy.ANCHOR_ONLY.value
    candidates = [text]
    if "." in text:
        candidates.append(text.rsplit(".", maxsplit=1)[-1])
    for candidate in candidates:
        try:
            return SnapshotValPolicy(candidate).value
        except Exception:
            pass
        enum_name = candidate.upper()
        if enum_name in SnapshotValPolicy.__members__:
            return SnapshotValPolicy[enum_name].value
    allowed_values = ", ".join(sorted(item.value for item in SnapshotValPolicy))
    allowed_names = ", ".join(sorted(item.name for item in SnapshotValPolicy))
    raise BadRequestAppException(
        f"invalid simulation mode snapshot_init.val_policy: {value}. "
        f"allowed values=[{allowed_values}], names=[{allowed_names}]"
    )


def _normalize_simulation_snapshot_init(raw: Any) -> dict[str, Any]:
    payload = raw if isinstance(raw, dict) else {}
    return {
        "train_seed_ratio": min(1.0, max(0.0, to_float(payload.get("train_seed_ratio"), 0.05))),
        "val_ratio": min(1.0, max(0.0, to_float(payload.get("val_ratio"), 0.1))),
        "test_ratio": min(1.0, max(0.0, to_float(payload.get("test_ratio"), 0.1))),
        "val_policy": _normalize_snapshot_val_policy(payload.get("val_policy")),
    }


def _normalize_training_include_label_ids(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    normalized: set[str] = set()
    for item in raw:
        text = str(item or "").strip()
        if not text:
            continue
        try:
            normalized.add(str(uuid.UUID(text)))
        except Exception as exc:
            raise BadRequestAppException(
                f"invalid config.training.include_label_ids item: {text}"
            ) from exc
    return sorted(normalized)


def _normalize_training_negative_sample_ratio(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, str) and not raw.strip():
        return 0.0
    try:
        value = float(raw)
    except Exception as exc:
        raise BadRequestAppException(
            f"invalid config.training.negative_sample_ratio: {raw}"
        ) from exc
    if (not math.isfinite(value)) or value < 0:
        raise BadRequestAppException(
            f"invalid config.training.negative_sample_ratio: {raw}. must be >= 0"
        )
    return value


def _normalize_training_config(raw: Any) -> dict[str, Any]:
    payload = raw if isinstance(raw, dict) else {}
    include_label_ids = _normalize_training_include_label_ids(payload.get("include_label_ids"))
    has_negative_sample_ratio = "negative_sample_ratio" in payload
    negative_sample_ratio = _normalize_training_negative_sample_ratio(
        payload.get("negative_sample_ratio", 0.0)
    )
    normalized: dict[str, Any] = {}
    if include_label_ids:
        normalized["include_label_ids"] = include_label_ids
    # 默认值为 0，不主动写入配置；仅在显式传入或非默认值时持久化。
    if has_negative_sample_ratio or negative_sample_ratio is None or (negative_sample_ratio or 0.0) > 0:
        normalized["negative_sample_ratio"] = negative_sample_ratio
    return normalized


def normalize_loop_config(raw_config: dict[str, Any] | None, *, mode: str) -> dict[str, Any]:
    config = dict(raw_config or {})
    plugin = config.get("plugin")
    sampling = config.get("sampling")
    mode_config = config.get("mode")
    reproducibility = config.get("reproducibility")
    execution = config.get("execution")
    training = config.get("training")

    normalized_plugin = dict(plugin) if isinstance(plugin, dict) else {}
    normalized_sampling = dict(sampling) if isinstance(sampling, dict) else {}
    normalized_mode = dict(mode_config) if isinstance(mode_config, dict) else {}
    reproducibility_map = dict(reproducibility) if isinstance(reproducibility, dict) else {}
    normalized_repro = {
        "global_seed": str(reproducibility_map.get("global_seed") or "").strip(),
        "deterministic_level": _normalize_deterministic_level(
            reproducibility_map.get("deterministic_level")
        ),
    }
    for seed_key in ("split_seed", "train_seed", "sampling_seed"):
        if seed_key in reproducibility_map:
            normalized_repro[seed_key] = _normalize_non_negative_seed(
                reproducibility_map.get(seed_key),
                field_name=seed_key,
            )
    normalized_execution = dict(execution) if isinstance(execution, dict) else {}
    normalized_training = _normalize_training_config(training)

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
    normalized_execution["preferred_executor_id"] = str(
        normalized_execution.get("preferred_executor_id")
        or normalized_execution.get("preferredExecutorId")
        or ""
    ).strip()
    normalized_execution.pop("preferredExecutorId", None)
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
        normalized_mode = {"confirm_required": False}
        normalized_sampling = {}
    elif mode == "active_learning":
        normalized_mode["confirm_required"] = to_bool(normalized_mode.get("confirm_required"), True)
    elif mode == "simulation":
        snapshot_init = _normalize_simulation_snapshot_init(normalized_mode.get("snapshot_init"))
        normalized_mode = {
            "oracle_commit_id": str(normalized_mode.get("oracle_commit_id") or "").strip(),
            "max_rounds": max(1, to_int(normalized_mode.get("max_rounds"), 20)),
            "finalize_train": to_bool(normalized_mode.get("finalize_train"), True),
            "snapshot_init": snapshot_init,
        }
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
    if normalized_training:
        normalized["training"] = normalized_training
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
    _normalize_deterministic_level(reproducibility_map.get("deterministic_level"))
    for seed_key in ("split_seed", "train_seed", "sampling_seed"):
        if seed_key in reproducibility_map:
            _normalize_non_negative_seed(reproducibility_map.get(seed_key), field_name=seed_key)

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
        try:
            uuid.UUID(oracle_commit_id)
        except Exception as exc:
            raise BadRequestAppException(
                "simulation mode requires valid UUID config.mode.oracle_commit_id"
            ) from exc
        snapshot_init = mode_map.get("snapshot_init")
        snapshot_init_map = snapshot_init if isinstance(snapshot_init, dict) else {}
        train_seed_ratio = to_float(snapshot_init_map.get("train_seed_ratio"), 0.05)
        val_ratio = to_float(snapshot_init_map.get("val_ratio"), 0.1)
        test_ratio = to_float(snapshot_init_map.get("test_ratio"), 0.1)
        for field_name, ratio in (
            ("train_seed_ratio", train_seed_ratio),
            ("val_ratio", val_ratio),
            ("test_ratio", test_ratio),
        ):
            if ratio < 0.0 or ratio > 1.0:
                raise BadRequestAppException(
                    f"simulation mode snapshot_init.{field_name} must be within [0, 1]"
                )
        _normalize_snapshot_val_policy(snapshot_init_map.get("val_policy"))


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


def extract_reproducibility_seed_overrides(
    raw_config: dict[str, Any] | None,
) -> tuple[int | None, int | None, int | None]:
    config = dict(raw_config or {})
    reproducibility = config.get("reproducibility")
    reproducibility_map = reproducibility if isinstance(reproducibility, dict) else {}

    def _extract(key: str) -> int | None:
        if key not in reproducibility_map:
            return None
        return _normalize_non_negative_seed(reproducibility_map.get(key), field_name=key)

    return (
        _extract("split_seed"),
        _extract("train_seed"),
        _extract("sampling_seed"),
    )


def extract_training_include_label_ids(raw_config: dict[str, Any] | None) -> list[str]:
    config = dict(raw_config or {})
    training = config.get("training")
    training_map = training if isinstance(training, dict) else {}
    return _normalize_training_include_label_ids(training_map.get("include_label_ids"))


def extract_training_negative_sample_ratio(raw_config: dict[str, Any] | None) -> float | None:
    config = dict(raw_config or {})
    training = config.get("training")
    training_map = training if isinstance(training, dict) else {}
    if "negative_sample_ratio" not in training_map:
        return 0.0
    return _normalize_training_negative_sample_ratio(training_map.get("negative_sample_ratio"))
