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
    train_project_dir: Path,
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
        "project": str(train_project_dir),
        "name": "yolo_train",
        "exist_ok": True,
        "verbose": False,
    }
    if deterministic:
        # 严格确定性：关闭多 worker 与 AMP，减少跨轮漂移。
        kwargs["workers"] = 0
        kwargs["amp"] = False
    return kwargs


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
    stop_flag: Event,
    load_yolo: LoadYoloFn,
    ensure_cjk_plot_font: EnsureFontFn,
    normalize_metrics: NormalizeMetricsFn,
    to_float: ToFloatFn,
    to_int: ToIntFn,
    yolo_task: str = "obb",
    epoch_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if stop_flag.is_set():
        raise RuntimeError("training stopped before start")

    _seed_reproducibility(train_seed, deterministic=deterministic)
    YOLO = load_yolo()
    ensure_cjk_plot_font()
    # Pass task= so YOLO knows whether to train detect or obb.
    model = YOLO(base_model, task=yolo_task)
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
            train_project_dir=train_project_dir,
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
    extra_artifacts = collect_optional_artifacts(save_dir=save_dir, workspace=workspace)
    return {
        "metrics": metrics,
        "history": history,
        "save_dir": str(save_dir),
        "best_path": str(final_best),
        "extra_artifacts": extra_artifacts,
    }


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
