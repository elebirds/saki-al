from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
import threading
from typing import Any, Awaitable, Callable

from saki_plugin_sdk import ExecutionBindingContext, PluginConfig, WorkspaceProtocol
from saki_plugin_yolo_det.common import to_yolo_device
from saki_plugin_yolo_det.types import TrainConfig
from saki_plugin_sdk.base import EventCallback


ToIntFn = Callable[[Any, int], int]
ToBoolFn = Callable[[Any, bool], bool]
ResolveModelRefFn = Callable[..., Awaitable[str]]
ResolveArchRefFn = Callable[..., Awaitable[str]]


def _format_epoch_metric_summary(metrics_row: dict[str, Any]) -> str:
    if not metrics_row:
        return "轮次指标：无数据"
    preferred = ("loss", "map50", "map50_95", "precision", "recall")
    ordered_keys: list[str] = []
    for key in preferred:
        if key in metrics_row:
            ordered_keys.append(key)
    for key in sorted(str(k) for k in metrics_row.keys()):
        if key not in ordered_keys:
            ordered_keys.append(key)
    chunks: list[str] = []
    for key in ordered_keys:
        try:
            value = float(metrics_row[key])
            chunks.append(f"{key}={value:.6f}")
        except Exception:
            chunks.append(f"{key}={metrics_row[key]}")
    return "轮次指标：" + ", ".join(chunks)


def _load_dataset_manifest(
    workspace: WorkspaceProtocol,
    *,
    strict: bool,
) -> dict[str, Any]:
    path = workspace.data_dir / "dataset_manifest.json"
    if not path.exists():
        if strict:
            raise RuntimeError(f"dataset manifest file not found: {path}")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        if strict:
            raise RuntimeError(f"failed to parse dataset manifest: {path}") from exc
        return {}
    if not isinstance(payload, dict):
        if strict:
            raise RuntimeError(f"dataset manifest must be an object: {path}")
        return {}
    return payload


def _extract_train_sample_count(
    manifest: dict[str, Any],
    *,
    strict: bool,
) -> int:
    raw = manifest.get("train_sample_count")
    try:
        count = int(raw)
    except Exception as exc:
        if strict:
            raise RuntimeError("dataset manifest train_sample_count must be a positive integer") from exc
        return 0
    if count <= 0:
        if strict:
            raise RuntimeError("dataset manifest train_sample_count must be > 0")
        return 0
    return count


def build_budget_summary(config: TrainConfig) -> dict[str, Any]:
    return {
        "mode": str(config.train_budget_mode),
        "requested_epochs": int(config.requested_epochs),
        "target_updates": int(config.target_updates),
        "train_sample_count": int(config.train_sample_count),
        "batch": int(config.batch),
        "steps_per_epoch": int(config.steps_per_epoch),
        "effective_epochs": int(config.effective_epochs or config.epochs),
        "effective_patience": int(config.effective_patience or config.patience),
    }


async def resolve_train_config(
    *,
    workspace: WorkspaceProtocol,
    plugin_config: PluginConfig,
    execution_context: ExecutionBindingContext,
    resolve_model_ref: ResolveModelRefFn,
    resolve_arch_ref: ResolveArchRefFn,
) -> TrainConfig:
    """Build a ``TrainConfig`` from a resolved ``PluginConfig``.

    All type coercion / defaults are already handled by ``PluginConfig``,
    so we can access fields directly.
    """
    requested_device = str(getattr(plugin_config, "device", "auto") or "auto").strip().lower()
    resolved_backend = str(execution_context.device_binding.backend or "").strip().lower()
    resolved_device_spec = str(execution_context.device_binding.device_spec or "").strip()
    if not resolved_backend:
        raise RuntimeError("execution binding backend is empty")
    device = to_yolo_device(resolved_backend, resolved_device_spec)
    requested_epochs = max(1, int(plugin_config.epochs))
    batch = max(1, int(plugin_config.batch))
    requested_patience = max(1, int(getattr(plugin_config, "patience", 20)))
    train_budget_mode = str(
        getattr(plugin_config, "train_budget_mode", "fixed_epochs") or "fixed_epochs"
    ).strip().lower()
    target_updates = max(0, int(getattr(plugin_config, "target_updates", 0) or 0))
    min_epochs = max(1, int(getattr(plugin_config, "min_epochs", 1) or 1))
    max_epochs = max(min_epochs, int(getattr(plugin_config, "max_epochs", 1000) or 1000))
    budget_disable_early_stop = bool(getattr(plugin_config, "budget_disable_early_stop", True))
    if train_budget_mode == "target_updates":
        manifest = _load_dataset_manifest(workspace, strict=True)
        train_sample_count = _extract_train_sample_count(manifest, strict=True)
        steps_per_epoch = max(1, math.ceil(train_sample_count / batch))
        effective_epochs = max(min_epochs, min(max_epochs, math.ceil(target_updates / steps_per_epoch)))
        effective_patience = effective_epochs + 1 if budget_disable_early_stop else requested_patience
    else:
        manifest = _load_dataset_manifest(workspace, strict=False)
        train_sample_count = _extract_train_sample_count(manifest, strict=False)
        steps_per_epoch = max(1, math.ceil(train_sample_count / batch)) if train_sample_count > 0 else 0
        effective_epochs = requested_epochs
        effective_patience = requested_patience
    resolved_base_model = await resolve_model_ref(
        workspace=workspace,
        params=plugin_config,
    )
    init_mode = str(getattr(plugin_config, "init_mode", "checkpoint_direct") or "checkpoint_direct").strip().lower()
    arch_yaml_ref = ""
    if init_mode == "arch_yaml_plus_weights":
        arch_yaml_ref = await resolve_arch_ref(
            workspace=workspace,
            params=plugin_config,
        )
    try:
        workers = int(getattr(plugin_config, "workers", 2))
    except Exception:
        workers = 2

    return TrainConfig(
        epochs=effective_epochs,
        batch=batch,
        imgsz=int(plugin_config.imgsz),
        patience=effective_patience,
        device=device,
        requested_device=requested_device,
        resolved_backend=resolved_backend,
        resolved_base_model=resolved_base_model,
        train_seed=max(0, int(getattr(plugin_config, "train_seed", 0) or 0)),
        deterministic=bool(getattr(plugin_config, "deterministic", False)),
        strong_deterministic=bool(getattr(plugin_config, "strong_deterministic", False)),
        yolo_task=str(plugin_config.yolo_task),
        cache=bool(getattr(plugin_config, "cache", False)),
        workers=max(0, min(32, workers)),
        init_mode=init_mode,
        arch_yaml_ref=str(arch_yaml_ref or ""),
        requested_epochs=requested_epochs,
        train_budget_mode=train_budget_mode,
        target_updates=target_updates,
        min_epochs=min_epochs,
        max_epochs=max_epochs,
        budget_disable_early_stop=budget_disable_early_stop,
        train_sample_count=train_sample_count,
        steps_per_epoch=steps_per_epoch,
        effective_epochs=effective_epochs,
        effective_patience=effective_patience,
    )


async def run_train_with_epoch_stream(
    *,
    workspace: WorkspaceProtocol,
    config: TrainConfig,
    emit: EventCallback,
    run_train_sync: Callable[..., dict[str, Any]],
    to_int: ToIntFn,
) -> dict[str, Any]:
    dataset_yaml = workspace.data_dir / "dataset.yaml"
    if not dataset_yaml.exists():
        raise RuntimeError(f"dataset file not found: {dataset_yaml}")
    effective_epochs = max(1, int(config.effective_epochs or config.epochs))
    effective_patience = max(1, int(config.effective_patience or config.patience))

    await emit(
        "log",
        {
            "level": "INFO",
            "message": (
                f"YOLO 训练开始 base_model={config.resolved_base_model} "
                f"init_mode={config.init_mode} "
                f"arch_yaml={config.arch_yaml_ref or '<none>'} "
                f"epochs={effective_epochs} batch={config.batch} imgsz={config.imgsz} "
                f"patience={effective_patience} requested_epochs={config.requested_epochs} "
                f"budget_mode={config.train_budget_mode} requested_device={config.requested_device} "
                f"resolved_backend={config.resolved_backend} device={config.device} "
                f"train_seed={config.train_seed} deterministic={config.deterministic} "
                f"strong_deterministic={config.strong_deterministic} "
                f"cache={config.cache} workers={config.workers}"
            ),
        },
    )

    loop = asyncio.get_running_loop()
    epoch_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def _on_epoch_update(payload: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(epoch_queue.put_nowait, payload)

    train_done = asyncio.Event()
    train_result: dict[str, Any] | None = None
    train_error: BaseException | None = None
    latest_epoch_metrics: dict[str, Any] = {}
    seen_epoch_keys: set[tuple[int, int]] = set()

    def _run_train() -> None:
        nonlocal train_result, train_error
        try:
            train_result = run_train_sync(
                workspace=workspace,
                dataset_yaml=dataset_yaml,
                base_model=config.resolved_base_model,
                epochs=effective_epochs,
                batch=config.batch,
                imgsz=config.imgsz,
                patience=effective_patience,
                device=config.device,
                train_seed=config.train_seed,
                deterministic=config.deterministic,
                strong_deterministic=config.strong_deterministic,
                yolo_task=config.yolo_task,
                init_mode=config.init_mode,
                arch_yaml_ref=config.arch_yaml_ref,
                cache=config.cache,
                workers=config.workers,
                epoch_callback=_on_epoch_update,
            )
        except BaseException as exc:  # pragma: no cover - delegated to caller path
            train_error = exc
        finally:
            loop.call_soon_threadsafe(train_done.set)

    train_thread = threading.Thread(
        target=_run_train,
        name=f"yolo-train-{workspace.task_id}",
        daemon=True,
    )
    train_thread.start()

    while True:
        if train_done.is_set() and epoch_queue.empty():
            break
        try:
            epoch_payload = await asyncio.wait_for(epoch_queue.get(), timeout=0.2)
        except asyncio.TimeoutError:
            continue
        step = max(1, to_int(epoch_payload.get("step"), 0))
        epoch = max(1, to_int(epoch_payload.get("epoch"), step))
        epoch_key = (step, epoch)
        if epoch_key in seen_epoch_keys:
            continue
        seen_epoch_keys.add(epoch_key)
        total_steps = max(1, to_int(epoch_payload.get("total_steps"), effective_epochs))
        eta_sec = max(0, to_int(epoch_payload.get("eta_sec"), 0))
        metrics_payload = epoch_payload.get("metrics")
        metrics_row = metrics_payload if isinstance(metrics_payload, dict) else {}
        if metrics_row:
            latest_epoch_metrics = dict(metrics_row)
        await emit(
            "progress",
            {
                "epoch": epoch,
                "step": step,
                "total_steps": total_steps,
                "eta_sec": eta_sec,
            },
        )
        await emit("metric", {"step": step, "epoch": epoch, "metrics": metrics_row})

    if train_error is not None:
        raise train_error
    if train_result is None:
        raise RuntimeError("training thread finished without result")
    best_metrics = (
        dict(train_result.get("metrics"))
        if isinstance(train_result.get("metrics"), dict)
        else {}
    )
    if best_metrics:
        train_result["metrics"] = dict(best_metrics)
        train_result["metrics_source"] = "train_output_best"
    elif latest_epoch_metrics:
        train_result["metrics"] = dict(latest_epoch_metrics)
        train_result["metrics_source"] = "last_metric_event_fallback"
    else:
        train_result["metrics"] = {}
        train_result["metrics_source"] = "none"
    train_result["best_metrics"] = dict(best_metrics)
    train_result["last_epoch_metrics"] = dict(latest_epoch_metrics)
    train_result["budget_summary"] = build_budget_summary(config)

    return train_result


def load_prepare_stats(workspace: WorkspaceProtocol) -> dict[str, Any]:
    return _load_dataset_manifest(workspace, strict=False)


def normalize_training_metrics(
    *,
    metrics: dict[str, Any],
    prepare_stats: dict[str, Any],
    to_int: ToIntFn,
    to_bool: ToBoolFn,
) -> dict[str, Any]:
    del prepare_stats, to_int, to_bool
    return dict(metrics)


def build_training_report_meta(
    *,
    prepare_stats: dict[str, Any],
    to_int: ToIntFn,
    to_bool: ToBoolFn,
) -> dict[str, Any]:
    return {
        "invalid_label_count": float(to_int(prepare_stats.get("invalid_label_count"), 0)),
        "val_degraded": 1.0 if to_bool(prepare_stats.get("val_degraded"), False) else 0.0,
    }
