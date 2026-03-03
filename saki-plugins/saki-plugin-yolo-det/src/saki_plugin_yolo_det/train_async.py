from __future__ import annotations

import asyncio
import json
from pathlib import Path
import threading
from typing import Any, Awaitable, Callable

from saki_plugin_sdk import ExecutionBindingContext, PluginConfig, WorkspaceProtocol
from saki_plugin_yolo_det.types import TrainConfig
from saki_plugin_sdk.base import EventCallback


ToIntFn = Callable[[Any, int], int]
ToBoolFn = Callable[[Any, bool], bool]
ResolveModelRefFn = Callable[..., Awaitable[str]]


def _to_yolo_device_spec(binding_backend: str, binding_device_spec: str) -> Any:
    backend = str(binding_backend or "").strip().lower()
    spec = str(binding_device_spec or "").strip().lower()
    if backend == "cuda":
        if spec.startswith("cuda:"):
            return spec.split(":", 1)[1] or "0"
        return spec or "0"
    if backend == "mps":
        return "mps"
    return "cpu"


def _format_epoch_metric_summary(metrics_row: dict[str, Any]) -> str:
    if not metrics_row:
        return "epoch metrics: no data"
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
    return "epoch metrics: " + ", ".join(chunks)


async def resolve_train_config(
    *,
    workspace: WorkspaceProtocol,
    plugin_config: PluginConfig,
    execution_context: ExecutionBindingContext,
    resolve_model_ref: ResolveModelRefFn,
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
    device = _to_yolo_device_spec(resolved_backend, resolved_device_spec)
    resolved_base_model = await resolve_model_ref(
        workspace=workspace,
        params=plugin_config,
    )
    return TrainConfig(
        epochs=int(plugin_config.epochs),
        batch=int(plugin_config.batch),
        imgsz=int(plugin_config.imgsz),
        patience=int(getattr(plugin_config, "patience", 20)),
        device=device,
        requested_device=requested_device,
        resolved_backend=resolved_backend,
        resolved_base_model=resolved_base_model,
        train_seed=max(0, int(getattr(plugin_config, "train_seed", 0) or 0)),
        deterministic=bool(getattr(plugin_config, "deterministic", False)),
        yolo_task=str(plugin_config.yolo_task),
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
        await emit(
            "log",
            {
                "level": "INFO",
                "message": _format_epoch_metric_summary(metrics_row),
                "meta": {
                    "source": "worker_metric_summary",
                    "epoch": epoch,
                    "step": step,
                },
            },
        )
        await emit("metric", {"step": step, "epoch": epoch, "metrics": metrics_row})

    if train_error is not None:
        raise train_error
    if train_result is None:
        raise RuntimeError("training thread finished without result")

    return train_result


def load_prepare_stats(workspace: WorkspaceProtocol) -> dict[str, Any]:
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
