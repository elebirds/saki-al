from __future__ import annotations

import os
import random
from pathlib import Path
from threading import Event
from typing import Any, Callable

from saki_plugin_sdk import WorkspaceProtocol
from saki_plugin_yolo_det.artifact_collector import (
    collect_optional_artifacts,
    copy_best_weights,
    extract_primary_metrics,
    resolve_save_dir,
)
from saki_plugin_yolo_det.metrics_parser import parse_results_csv

ToFloatFn = Callable[[Any, float], float]
ToIntFn = Callable[[Any, int], int]
NormalizeMetricsFn = Callable[[dict[str, Any] | Any], dict[str, float]]
LoadYoloFn = Callable[[], Any]
EnsureFontFn = Callable[[], None]


def _collect_epoch_raw_metrics(*, trainer: Any, to_float: ToFloatFn) -> dict[str, float]:
    merged: dict[str, float] = {}
    metrics_payload = getattr(trainer, "metrics", {}) or {}
    if isinstance(metrics_payload, dict):
        for key, value in metrics_payload.items():
            merged[str(key)] = to_float(value, 0.0)

    labeler = getattr(trainer, "label_loss_items", None)
    if callable(labeler):
        tloss = getattr(trainer, "tloss", None)
        try:
            labeled_loss = labeler(tloss, prefix="train")
        except TypeError:
            labeled_loss = labeler(tloss)
        if isinstance(labeled_loss, dict):
            for key, value in labeled_loss.items():
                merged[str(key)] = to_float(value, 0.0)
    return merged


def _seed_reproducibility(train_seed: int, *, deterministic: bool) -> None:
    seed = max(0, int(train_seed))
    random.seed(seed)

    try:
        import numpy as np  # type: ignore

        np.random.seed(seed)
    except Exception:
        pass

    try:
        import torch  # type: ignore

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        if deterministic:
            # 官方推荐的确定性配置，避免同 seed 训练产生漂移。
            os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
            try:
                torch.use_deterministic_algorithms(True, warn_only=True)
            except Exception:
                pass
            try:
                torch.backends.cudnn.deterministic = True
                torch.backends.cudnn.benchmark = False
            except Exception:
                pass
    except Exception:
        pass


def _build_train_kwargs(
    *,
    dataset_yaml: Path,
    epochs: int,
    batch: int,
    imgsz: int,
    patience: int,
    device: Any,
    train_seed: int,
    deterministic: bool,
    strong_deterministic: bool,
    cache: bool = False,
    workers: int = 2,
    train_project_dir: Path,
    init_mode: str = "checkpoint_direct",
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "data": str(dataset_yaml),
        "epochs": int(epochs),
        "batch": int(batch),
        "imgsz": int(imgsz),
        "patience": int(patience),
        "device": device,
        "seed": int(train_seed),
        "deterministic": bool(deterministic),
        "workers": max(0, int(workers)),
        "project": str(train_project_dir),
        "name": "yolo_train",
        "exist_ok": True,
        "verbose": False,
    }
    if strong_deterministic:
        # 严格确定性：关闭多 worker 与 AMP，减少跨轮漂移。
        kwargs["workers"] = 0
        kwargs["amp"] = False
    if cache:
        kwargs["cache"] = "ram"
    if str(init_mode).strip().lower() == "arch_yaml_plus_weights":
        # 新模式下禁用 Ultralytics 默认预训练注入，避免引入隐式先验。
        kwargs["pretrained"] = False
    return kwargs


def _has_shape_tensor(value: Any) -> bool:
    return hasattr(value, "shape")


def _looks_like_state_dict(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    return any(_has_shape_tensor(value) for value in payload.values())


def _extract_model_state_dict(model_obj: Any) -> dict[str, Any]:
    state_fn = getattr(model_obj, "state_dict", None)
    if not callable(state_fn):
        return {}
    try:
        state = state_fn()
    except Exception:
        return {}
    if not isinstance(state, dict):
        return {}
    return {str(key): value for key, value in state.items()}


def _extract_state_dict_from_checkpoint_payload(payload: Any) -> dict[str, Any]:
    if _looks_like_state_dict(payload):
        return {str(key): value for key, value in payload.items()}
    if isinstance(payload, dict):
        state_dict_payload = payload.get("state_dict")
        if _looks_like_state_dict(state_dict_payload):
            return {str(key): value for key, value in state_dict_payload.items()}
        model_payload = payload.get("model")
        model_state = _extract_model_state_dict(model_payload)
        if model_state:
            return model_state
        if _looks_like_state_dict(model_payload):
            return {str(key): value for key, value in model_payload.items()}
    return {}


def _candidate_target_keys(source_key: str) -> tuple[str, ...]:
    key = str(source_key or "")
    if not key:
        return tuple()
    candidates = [key]
    if key.startswith("model."):
        candidates.append(key[6:])
    else:
        candidates.append(f"model.{key}")
    seen: set[str] = set()
    ordered: list[str] = []
    for item in candidates:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return tuple(ordered)


def _match_state_dict_by_shape(
    *,
    source_state: dict[str, Any],
    target_state: dict[str, Any],
) -> tuple[dict[str, Any], int, int, list[str]]:
    matched: dict[str, Any] = {}
    shape_mismatch = 0
    missing_in_target = 0
    unmatched_samples: list[str] = []
    for source_key, source_value in source_state.items():
        target_key = next((item for item in _candidate_target_keys(source_key) if item in target_state), "")
        if not target_key:
            missing_in_target += 1
            if len(unmatched_samples) < 10:
                unmatched_samples.append(str(source_key))
            continue
        target_value = target_state.get(target_key)
        if not (_has_shape_tensor(source_value) and _has_shape_tensor(target_value)):
            shape_mismatch += 1
            if len(unmatched_samples) < 10:
                unmatched_samples.append(str(source_key))
            continue
        if tuple(source_value.shape) != tuple(target_value.shape):
            shape_mismatch += 1
            if len(unmatched_samples) < 10:
                unmatched_samples.append(str(source_key))
            continue
        matched[target_key] = source_value
    return matched, shape_mismatch, missing_in_target, unmatched_samples


def _load_source_state_dict(
    *,
    YOLO: Any,
    weights_ref: str,
) -> tuple[dict[str, Any], str]:
    yolo_error: Exception | None = None
    try:
        source_model = YOLO(weights_ref)
        source_state = _extract_model_state_dict(getattr(source_model, "model", None))
        if source_state:
            return source_state, "yolo_model"
    except Exception as exc:  # pragma: no cover - fallback path
        yolo_error = exc

    torch_error: Exception | None = None
    try:
        import torch  # type: ignore

        checkpoint = torch.load(weights_ref, map_location="cpu")
        source_state = _extract_state_dict_from_checkpoint_payload(checkpoint)
        if source_state:
            return source_state, "torch_checkpoint"
    except Exception as exc:  # pragma: no cover - fallback path
        torch_error = exc

    details = []
    if yolo_error is not None:
        details.append(f"yolo_load={type(yolo_error).__name__}: {yolo_error}")
    if torch_error is not None:
        details.append(f"torch_load={type(torch_error).__name__}: {torch_error}")
    joined = "; ".join(details) if details else "no parser available"
    raise RuntimeError(f"failed to read source weights state_dict from {weights_ref}: {joined}")


def _build_training_model(
    *,
    YOLO: Any,
    base_model: str,
    yolo_task: str,
    init_mode: str,
    arch_yaml_ref: str,
) -> tuple[Any, dict[str, Any]]:
    mode = str(init_mode or "checkpoint_direct").strip().lower()
    if mode != "arch_yaml_plus_weights":
        return YOLO(base_model, task=yolo_task), {}

    arch_ref = str(arch_yaml_ref or "").strip()
    if not arch_ref:
        raise RuntimeError("arch_yaml_ref is required when init_mode=arch_yaml_plus_weights")
    model = YOLO(arch_ref, task=yolo_task)
    model_core = getattr(model, "model", None)
    load_fn = getattr(model_core, "load_state_dict", None)
    if not callable(load_fn):
        raise RuntimeError("target yolo model does not expose load_state_dict")
    target_state = _extract_model_state_dict(model_core)
    if not target_state:
        raise RuntimeError("target yolo model state_dict is empty")

    source_state, source_kind = _load_source_state_dict(
        YOLO=YOLO,
        weights_ref=base_model,
    )
    matched_state, shape_mismatch, missing_in_target, unmatched_samples = _match_state_dict_by_shape(
        source_state=source_state,
        target_state=target_state,
    )
    loaded_count = len(matched_state)
    if loaded_count <= 0:
        raise RuntimeError(
            "init_mode=arch_yaml_plus_weights loaded 0 tensors after key+shape matching; "
            f"arch_yaml={arch_ref} weights_ref={base_model}"
        )
    load_fn(matched_state, strict=False)
    summary = {
        "mode": mode,
        "arch_yaml": arch_ref,
        "weights_ref": base_model,
        "source_kind": source_kind,
        "source_tensors": int(len(source_state)),
        "target_tensors": int(len(target_state)),
        "loaded_tensors": int(loaded_count),
        "shape_mismatch_tensors": int(shape_mismatch),
        "missing_in_target_tensors": int(missing_in_target),
        "sample_unmatched_keys": list(unmatched_samples),
    }
    return model, summary


def run_train_sync(
    *,
    workspace: WorkspaceProtocol,
    dataset_yaml: Path,
    base_model: str,
    epochs: int,
    batch: int,
    imgsz: int,
    patience: int,
    device: Any,
    train_seed: int,
    deterministic: bool,
    strong_deterministic: bool,
    cache: bool = False,
    workers: int = 2,
    stop_flag: Event,
    load_yolo: LoadYoloFn,
    ensure_cjk_plot_font: EnsureFontFn,
    normalize_metrics: NormalizeMetricsFn,
    to_float: ToFloatFn,
    to_int: ToIntFn,
    yolo_task: str = "obb",
    init_mode: str = "checkpoint_direct",
    arch_yaml_ref: str = "",
    epoch_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if stop_flag.is_set():
        raise RuntimeError("training stopped before start")

    _seed_reproducibility(train_seed, deterministic=deterministic)
    YOLO = load_yolo()
    ensure_cjk_plot_font()
    # Pass task= so YOLO knows whether to train detect or obb.
    model, init_load_summary = _build_training_model(
        YOLO=YOLO,
        base_model=base_model,
        yolo_task=yolo_task,
        init_mode=init_mode,
        arch_yaml_ref=arch_yaml_ref,
    )
    model.add_callback(
        "on_fit_epoch_end",
        _build_epoch_update_callback(
            stop_flag=stop_flag,
            epochs=epochs,
            normalize_metrics=normalize_metrics,
            to_float=to_float,
            to_int=to_int,
            epoch_callback=epoch_callback,
        ),
    )
    # Use an absolute project directory under workspace artifacts to avoid
    # Ultralytics falling back to its default "runs/detect" tree.
    train_project_dir = workspace.artifacts_dir.resolve()
    train_output = model.train(
        **_build_train_kwargs(
            dataset_yaml=dataset_yaml,
            epochs=epochs,
            batch=batch,
            imgsz=imgsz,
            patience=patience,
            device=device,
            train_seed=train_seed,
            deterministic=deterministic,
            strong_deterministic=strong_deterministic,
            cache=cache,
            workers=workers,
            train_project_dir=train_project_dir,
            init_mode=init_mode,
        )
    )
    if stop_flag.is_set():
        raise RuntimeError("training stopped")

    save_dir = resolve_save_dir(train_output, model)
    final_best = copy_best_weights(save_dir=save_dir, workspace=workspace)
    history = parse_results_csv(save_dir / "results.csv", to_float=to_float)
    metrics = extract_primary_metrics(
        train_output=train_output,
        history=history,
        to_float=to_float,
    )
    trainer = getattr(model, "trainer", None)
    stopped_epoch_raw = getattr(trainer, "epoch", None) if trainer is not None else None
    stopped_epoch = (
        max(1, to_int(stopped_epoch_raw, 0) + 1)
        if stopped_epoch_raw is not None
        else len(history)
    )
    best_epoch_raw = getattr(trainer, "best_epoch", None) if trainer is not None else None
    best_epoch = (
        max(1, to_int(best_epoch_raw, 0) + 1)
        if best_epoch_raw is not None and to_int(best_epoch_raw, -1) >= 0
        else (stopped_epoch if history else 0)
    )
    early_stop_triggered = (
        (not stop_flag.is_set())
        and int(epochs) > 0
        and int(stopped_epoch) > 0
        and int(stopped_epoch) < int(epochs)
    )
    train_summary = {
        "patience": int(patience),
        "requested_epochs": int(epochs),
        "best_epoch": int(best_epoch) if best_epoch > 0 else None,
        "stopped_epoch": int(stopped_epoch) if stopped_epoch > 0 else None,
        "early_stop_triggered": bool(early_stop_triggered),
    }
    extra_artifacts = collect_optional_artifacts(save_dir=save_dir, workspace=workspace)
    output = {
        "metrics": metrics,
        "history": history,
        "save_dir": str(save_dir),
        "best_path": str(final_best),
        "extra_artifacts": extra_artifacts,
        "train_summary": train_summary,
    }
    if init_load_summary:
        output["init_load_summary"] = dict(init_load_summary)
    return output


def _build_epoch_update_callback(
    *,
    stop_flag: Event,
    epochs: int,
    normalize_metrics: NormalizeMetricsFn,
    to_float: ToFloatFn,
    to_int: ToIntFn,
    epoch_callback: Callable[[dict[str, Any]], None] | None = None,
) -> Callable[[Any], None]:
    def _emit_epoch_update(trainer: Any) -> None:
        if stop_flag.is_set():
            setattr(trainer, "stop", True)
            return
        if epoch_callback is None:
            return
        epoch = int(getattr(trainer, "epoch", -1)) + 1
        total_steps = max(1, to_int(getattr(trainer, "epochs", epochs), epochs))
        epoch_time = to_float(getattr(trainer, "epoch_time", 0.0), 0.0)
        remaining_epochs = max(0, total_steps - epoch)
        eta_sec = int(max(0.0, epoch_time * remaining_epochs)) if epoch_time > 0 else 0
        raw_metrics = _collect_epoch_raw_metrics(trainer=trainer, to_float=to_float)
        epoch_callback(
            {
                "step": max(1, epoch),
                "epoch": max(1, epoch),
                "total_steps": total_steps,
                "eta_sec": eta_sec,
                "metrics": normalize_metrics(raw_metrics),
            }
        )

    return _emit_epoch_update
