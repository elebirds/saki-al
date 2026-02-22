from __future__ import annotations

import asyncio
import json
from pathlib import Path
import threading
from typing import Any, Awaitable, Callable

from saki_plugin_sdk import PluginConfig, Workspace
from saki_plugin_yolo_det.types import TrainConfig
from saki_plugin_sdk.base import EventCallback


ToIntFn = Callable[[Any, int], int]
ToBoolFn = Callable[[Any, bool], bool]
ResolveDeviceFn = Callable[[Any], tuple[Any, str, str]]
ResolveModelRefFn = Callable[..., Awaitable[str]]


async def resolve_train_config(
    *,
    workspace: Workspace,
    plugin_config: PluginConfig,
    resolve_device: ResolveDeviceFn,
    resolve_model_ref: ResolveModelRefFn,
) -> TrainConfig:
    """Build a ``TrainConfig`` from a resolved ``PluginConfig``.

    All type coercion / defaults are already handled by ``PluginConfig``,
    so we can access fields directly.
    """
    device, requested_device, resolved_backend = resolve_device(plugin_config)
    resolved_base_model = await resolve_model_ref(
        workspace=workspace,
        params=plugin_config,
    )
    return TrainConfig(
        epochs=int(plugin_config.epochs),
        batch=int(plugin_config.batch),
        imgsz=int(plugin_config.imgsz),
        patience=int(plugin_config.get("patience", 20)),
        device=device,
        requested_device=requested_device,
        resolved_backend=resolved_backend,
        resolved_base_model=resolved_base_model,
        train_seed=max(0, int(plugin_config.get("train_seed", 0) or 0)),
        deterministic=bool(plugin_config.get("deterministic", False)),
        yolo_task=str(plugin_config.yolo_task),
    )


async def run_train_with_epoch_stream(
    *,
    workspace: Workspace,
    config: TrainConfig,
    emit: EventCallback,
    run_train_sync: Callable[..., dict[str, Any]],
    to_int: ToIntFn,
) -> dict[str, Any]:
    dataset_yaml = workspace.data_dir / "dataset.yaml"
    if not dataset_yaml.exists():
        raise RuntimeError(f"dataset file not found: {dataset_yaml}")

    await emit(
        "log",
        {
            "level": "INFO",
            "message": (
                f"YOLO training started base_model={config.resolved_base_model} "
                f"epochs={config.epochs} batch={config.batch} imgsz={config.imgsz} "
                f"patience={config.patience} requested_device={config.requested_device} "
                f"resolved_backend={config.resolved_backend} device={config.device} "
                f"train_seed={config.train_seed} deterministic={config.deterministic}"
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

    def _run_train() -> None:
        nonlocal train_result, train_error
        try:
            train_result = run_train_sync(
                workspace=workspace,
                dataset_yaml=dataset_yaml,
                base_model=config.resolved_base_model,
                epochs=config.epochs,
                batch=config.batch,
                imgsz=config.imgsz,
                patience=config.patience,
                device=config.device,
                train_seed=config.train_seed,
                deterministic=config.deterministic,
                yolo_task=config.yolo_task,
                epoch_callback=_on_epoch_update,
            )
        except BaseException as exc:  # pragma: no cover - delegated to caller path
            train_error = exc
        finally:
            loop.call_soon_threadsafe(train_done.set)

    train_thread = threading.Thread(
        target=_run_train,
        name=f"yolo-train-{workspace.step_id}",
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
        total_steps = max(1, to_int(epoch_payload.get("total_steps"), config.epochs))
        eta_sec = max(0, to_int(epoch_payload.get("eta_sec"), 0))
        metrics_payload = epoch_payload.get("metrics")
        metrics_row = metrics_payload if isinstance(metrics_payload, dict) else {}
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

    return train_result


def load_prepare_stats(workspace: Workspace) -> dict[str, Any]:
    path = workspace.data_dir / "dataset_manifest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def normalize_training_metrics(
    *,
    metrics: dict[str, Any],
    prepare_stats: dict[str, Any],
    to_int: ToIntFn,
    to_bool: ToBoolFn,
) -> dict[str, Any]:
    merged = dict(metrics)
    merged.setdefault("invalid_label_count", float(to_int(prepare_stats.get("invalid_label_count"), 0)))
    merged.setdefault("val_degraded", 1.0 if to_bool(prepare_stats.get("val_degraded"), False) else 0.0)
    return merged
