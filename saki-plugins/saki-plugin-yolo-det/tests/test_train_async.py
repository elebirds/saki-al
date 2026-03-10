from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from saki_plugin_yolo_det.train_async import (
    _format_epoch_metric_summary,
    build_budget_summary,
    resolve_train_config,
    run_train_with_epoch_stream,
)
from saki_plugin_yolo_det.types import TrainConfig


class _WorkspaceStub:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.data_dir = root / "data"
        self.task_id = "step-train-async"
        self.data_dir.mkdir(parents=True, exist_ok=True)


def _write_dataset_manifest(workspace: _WorkspaceStub, *, train_sample_count: int) -> None:
    (workspace.data_dir / "dataset_manifest.json").write_text(
        json.dumps({"train_sample_count": train_sample_count}),
        encoding="utf-8",
    )


def _make_train_config() -> TrainConfig:
    return TrainConfig(
        epochs=2,
        batch=4,
        imgsz=640,
        patience=5,
        device="cpu",
        requested_device="cpu",
        resolved_backend="cpu",
        resolved_base_model="yolo11n.pt",
        train_seed=0,
        deterministic=False,
        strong_deterministic=False,
        yolo_task="obb",
        workers=2,
        requested_epochs=2,
        train_budget_mode="fixed_epochs",
        target_updates=0,
        min_epochs=1,
        max_epochs=1000,
        budget_disable_early_stop=True,
        train_sample_count=8,
        steps_per_epoch=2,
        effective_epochs=2,
        effective_patience=5,
    )


@pytest.mark.anyio
async def test_run_train_with_epoch_stream_emits_progress_then_log_then_metric(tmp_path):
    workspace = _WorkspaceStub(tmp_path)
    (workspace.data_dir / "dataset.yaml").write_text("path: .\ntrain: images\nval: images\n", encoding="utf-8")
    config = _make_train_config()

    emitted: list[tuple[str, dict[str, Any]]] = []

    async def _emit(event_type: str, payload: dict[str, Any]) -> None:
        emitted.append((event_type, payload))

    def _run_train_sync(**kwargs):
        assert kwargs["workers"] == 2
        assert kwargs["epochs"] == 2
        assert kwargs["patience"] == 5
        callback = kwargs["epoch_callback"]
        callback(
            {
                "step": 1,
                "epoch": 1,
                "total_steps": 2,
                "eta_sec": 5,
                "metrics": {"loss": 0.5, "map50": 0.2},
            }
        )
        callback(
            {
                "step": 2,
                "epoch": 2,
                "total_steps": 2,
                "eta_sec": 0,
                "metrics": {"loss": 0.4, "map50": 0.3},
            }
        )
        return {"metrics": {"loss": 0.4, "map50": 0.3}}

    await run_train_with_epoch_stream(
        workspace=workspace,  # type: ignore[arg-type]
        config=config,
        emit=_emit,
        run_train_sync=_run_train_sync,
        to_int=lambda value, default: int(value) if value is not None else default,
    )

    # 首条是训练开始日志，后续每个 epoch 固定为 progress -> metric
    epoch_rows = emitted[1:]
    assert [item[0] for item in epoch_rows] == [
        "progress",
        "metric",
        "progress",
        "metric",
    ]


@pytest.mark.anyio
async def test_run_train_with_epoch_stream_uses_train_output_best_metrics_as_final(tmp_path):
    workspace = _WorkspaceStub(tmp_path)
    (workspace.data_dir / "dataset.yaml").write_text("path: .\ntrain: images\nval: images\n", encoding="utf-8")
    config = _make_train_config()

    emitted: list[tuple[str, dict[str, Any]]] = []

    async def _emit(event_type: str, payload: dict[str, Any]) -> None:
        emitted.append((event_type, payload))

    def _run_train_sync(**kwargs):
        assert kwargs["workers"] == 2
        assert kwargs["epochs"] == 2
        assert kwargs["patience"] == 5
        callback = kwargs["epoch_callback"]
        callback(
            {
                "step": 2,
                "epoch": 2,
                "total_steps": 2,
                "eta_sec": 0,
                "metrics": {"loss": 0.4, "map50": 0.3, "map50_95": 0.2, "precision": 0.5, "recall": 0.6},
            }
        )
        # simulate final best.pt validate callback on the same epoch
        callback(
            {
                "step": 2,
                "epoch": 2,
                "total_steps": 2,
                "eta_sec": 0,
                "metrics": {"loss": 0.45, "map50": 0.35, "map50_95": 0.25, "precision": 0.55, "recall": 0.65},
            }
        )
        return {
            "metrics": {"loss": 0.4, "map50": 0.3, "map50_95": 0.2, "precision": 0.5, "recall": 0.6},
        }

    output = await run_train_with_epoch_stream(
        workspace=workspace,  # type: ignore[arg-type]
        config=config,
        emit=_emit,
        run_train_sync=_run_train_sync,
        to_int=lambda value, default: int(value) if value is not None else default,
    )

    assert output["metrics"]["loss"] == pytest.approx(0.4)
    assert output["metrics"]["map50"] == pytest.approx(0.3)
    assert output["metrics"]["map50_95"] == pytest.approx(0.2)
    assert output["metrics"]["precision"] == pytest.approx(0.5)
    assert output["metrics"]["recall"] == pytest.approx(0.6)
    assert output["metrics_source"] == "train_output_best"
    assert output["last_epoch_metrics"]["loss"] == pytest.approx(0.4)
    assert output["budget_summary"] == build_budget_summary(config)

    # 同一 step/epoch 的重复回调应被去重，只保留首条 progress+metric
    epoch_rows = emitted[1:]
    assert [item[0] for item in epoch_rows] == ["progress", "metric"]
    assert epoch_rows[1][1]["step"] == 2
    assert epoch_rows[1][1]["epoch"] == 2
    assert epoch_rows[1][1]["metrics"]["loss"] == pytest.approx(0.4)


def test_format_epoch_metric_summary_prioritizes_common_keys():
    text = _format_epoch_metric_summary(
        {"map50": 0.22, "extra": 1.0, "loss": 0.44, "precision": 0.33}
    )
    assert text.startswith("轮次指标：loss=")
    assert "map50=" in text
    assert "precision=" in text
    assert "extra=" in text


@pytest.mark.anyio
async def test_resolve_train_config_reads_cache_flag_and_workers(tmp_path: Path):
    workspace = _WorkspaceStub(tmp_path)
    _write_dataset_manifest(workspace, train_sample_count=24)
    plugin_config = SimpleNamespace(
        epochs=3,
        batch=4,
        imgsz=640,
        patience=7,
        device="auto",
        train_seed=11,
        deterministic=False,
        strong_deterministic=False,
        yolo_task="detect",
        cache=True,
        workers=6,
        train_budget_mode="fixed_epochs",
        target_updates=0,
        min_epochs=1,
        max_epochs=1000,
        budget_disable_early_stop=True,
    )
    execution_context = SimpleNamespace(
        device_binding=SimpleNamespace(backend="cpu", device_spec="cpu"),
    )

    async def _resolve_model_ref(**kwargs):
        del kwargs
        return "yolov8n.pt"

    async def _resolve_arch_ref(**kwargs):
        del kwargs
        return ""

    resolved = await resolve_train_config(
        workspace=workspace,  # type: ignore[arg-type]
        plugin_config=plugin_config,  # type: ignore[arg-type]
        execution_context=execution_context,  # type: ignore[arg-type]
        resolve_model_ref=_resolve_model_ref,
        resolve_arch_ref=_resolve_arch_ref,
    )
    assert resolved.cache is True
    assert resolved.workers == 6
    assert resolved.init_mode == "checkpoint_direct"
    assert resolved.arch_yaml_ref == ""
    assert resolved.train_budget_mode == "fixed_epochs"
    assert resolved.requested_epochs == 3
    assert resolved.epochs == 3
    assert resolved.patience == 7
    assert resolved.train_sample_count == 24
    assert resolved.steps_per_epoch == 6


@pytest.mark.anyio
async def test_resolve_train_config_target_updates_computes_effective_epochs(tmp_path: Path):
    workspace = _WorkspaceStub(tmp_path)
    _write_dataset_manifest(workspace, train_sample_count=550)
    plugin_config = SimpleNamespace(
        epochs=300,
        batch=32,
        imgsz=640,
        patience=20,
        device="auto",
        train_seed=11,
        deterministic=False,
        strong_deterministic=False,
        yolo_task="detect",
        cache=False,
        workers=4,
        train_budget_mode="target_updates",
        target_updates=3000,
        min_epochs=20,
        max_epochs=300,
        budget_disable_early_stop=True,
    )
    execution_context = SimpleNamespace(
        device_binding=SimpleNamespace(backend="cpu", device_spec="cpu"),
    )

    async def _resolve_model_ref(**kwargs):
        del kwargs
        return "yolov8s-cls.pt"

    async def _resolve_arch_ref(**kwargs):
        del kwargs
        return ""

    resolved = await resolve_train_config(
        workspace=workspace,  # type: ignore[arg-type]
        plugin_config=plugin_config,  # type: ignore[arg-type]
        execution_context=execution_context,  # type: ignore[arg-type]
        resolve_model_ref=_resolve_model_ref,
        resolve_arch_ref=_resolve_arch_ref,
    )

    assert resolved.requested_epochs == 300
    assert resolved.train_budget_mode == "target_updates"
    assert resolved.target_updates == 3000
    assert resolved.train_sample_count == 550
    assert resolved.steps_per_epoch == 18
    assert resolved.effective_epochs == 167
    assert resolved.epochs == 167
    assert resolved.effective_patience == 168
    assert resolved.patience == 168


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("target_updates", "min_epochs", "max_epochs", "expected_epochs"),
    [
        (10, 20, 300, 20),
        (100000, 20, 50, 50),
    ],
)
async def test_resolve_train_config_target_updates_clamps_epochs(
    tmp_path: Path,
    target_updates: int,
    min_epochs: int,
    max_epochs: int,
    expected_epochs: int,
):
    workspace = _WorkspaceStub(tmp_path)
    _write_dataset_manifest(workspace, train_sample_count=550)
    plugin_config = SimpleNamespace(
        epochs=999,
        batch=32,
        imgsz=640,
        patience=12,
        device="auto",
        train_seed=0,
        deterministic=False,
        strong_deterministic=False,
        yolo_task="detect",
        cache=False,
        workers=2,
        train_budget_mode="target_updates",
        target_updates=target_updates,
        min_epochs=min_epochs,
        max_epochs=max_epochs,
        budget_disable_early_stop=False,
    )
    execution_context = SimpleNamespace(
        device_binding=SimpleNamespace(backend="cpu", device_spec="cpu"),
    )

    async def _resolve_model_ref(**kwargs):
        del kwargs
        return "yolov8s-cls.pt"

    async def _resolve_arch_ref(**kwargs):
        del kwargs
        return ""

    resolved = await resolve_train_config(
        workspace=workspace,  # type: ignore[arg-type]
        plugin_config=plugin_config,  # type: ignore[arg-type]
        execution_context=execution_context,  # type: ignore[arg-type]
        resolve_model_ref=_resolve_model_ref,
        resolve_arch_ref=_resolve_arch_ref,
    )

    assert resolved.effective_epochs == expected_epochs
    assert resolved.epochs == expected_epochs
    assert resolved.effective_patience == 12
    assert resolved.patience == 12


@pytest.mark.anyio
async def test_resolve_train_config_target_updates_requires_dataset_manifest(tmp_path: Path):
    workspace = _WorkspaceStub(tmp_path)
    plugin_config = SimpleNamespace(
        epochs=300,
        batch=32,
        imgsz=640,
        patience=20,
        device="auto",
        train_seed=0,
        deterministic=False,
        strong_deterministic=False,
        yolo_task="detect",
        cache=False,
        workers=2,
        train_budget_mode="target_updates",
        target_updates=3000,
        min_epochs=20,
        max_epochs=300,
        budget_disable_early_stop=True,
    )
    execution_context = SimpleNamespace(
        device_binding=SimpleNamespace(backend="cpu", device_spec="cpu"),
    )

    async def _resolve_model_ref(**kwargs):
        del kwargs
        return "yolov8s-cls.pt"

    async def _resolve_arch_ref(**kwargs):
        del kwargs
        return ""

    with pytest.raises(RuntimeError, match="dataset manifest file not found"):
        await resolve_train_config(
            workspace=workspace,  # type: ignore[arg-type]
            plugin_config=plugin_config,  # type: ignore[arg-type]
            execution_context=execution_context,  # type: ignore[arg-type]
            resolve_model_ref=_resolve_model_ref,
            resolve_arch_ref=_resolve_arch_ref,
        )


@pytest.mark.anyio
async def test_resolve_train_config_target_updates_requires_positive_train_sample_count(tmp_path: Path):
    workspace = _WorkspaceStub(tmp_path)
    _write_dataset_manifest(workspace, train_sample_count=0)
    plugin_config = SimpleNamespace(
        epochs=300,
        batch=32,
        imgsz=640,
        patience=20,
        device="auto",
        train_seed=0,
        deterministic=False,
        strong_deterministic=False,
        yolo_task="detect",
        cache=False,
        workers=2,
        train_budget_mode="target_updates",
        target_updates=3000,
        min_epochs=20,
        max_epochs=300,
        budget_disable_early_stop=True,
    )
    execution_context = SimpleNamespace(
        device_binding=SimpleNamespace(backend="cpu", device_spec="cpu"),
    )

    async def _resolve_model_ref(**kwargs):
        del kwargs
        return "yolov8s-cls.pt"

    async def _resolve_arch_ref(**kwargs):
        del kwargs
        return ""

    with pytest.raises(RuntimeError, match="train_sample_count must be > 0"):
        await resolve_train_config(
            workspace=workspace,  # type: ignore[arg-type]
            plugin_config=plugin_config,  # type: ignore[arg-type]
            execution_context=execution_context,  # type: ignore[arg-type]
            resolve_model_ref=_resolve_model_ref,
            resolve_arch_ref=_resolve_arch_ref,
        )
