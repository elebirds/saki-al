from __future__ import annotations

from pathlib import Path
from threading import Event

import pytest

from saki_plugin_yolo_det.metrics_parser import normalize_metrics
from saki_plugin_yolo_det.train_sync_runner import (
    _build_epoch_update_callback,
    _build_training_model,
    _build_train_kwargs,
    _collect_epoch_raw_metrics,
)


def _to_float(value, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _to_int(value, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


class _DummyTrainer:
    epoch = 0
    epochs = 5
    epoch_time = 1.5
    tloss = [0.1, 0.2, 0.3]
    metrics = {"metrics/mAP50(B)": 0.73, "metrics/precision(B)": 0.8}

    @staticmethod
    def label_loss_items(loss_items=None, prefix: str = "train"):
        keys = [f"{prefix}/box_loss", f"{prefix}/cls_loss", f"{prefix}/dfl_loss"]
        if loss_items is None:
            return keys
        return dict(zip(keys, loss_items))


def test_collect_epoch_raw_metrics_merges_train_loss_and_validation_metrics():
    merged = _collect_epoch_raw_metrics(trainer=_DummyTrainer(), to_float=_to_float)
    assert merged["metrics/mAP50(B)"] == pytest.approx(0.73)
    assert merged["metrics/precision(B)"] == pytest.approx(0.8)
    assert merged["train/box_loss"] == pytest.approx(0.1)
    assert merged["train/cls_loss"] == pytest.approx(0.2)
    assert merged["train/dfl_loss"] == pytest.approx(0.3)


def test_epoch_callback_emits_loss_after_metric_merge():
    captured: list[dict] = []
    callback = _build_epoch_update_callback(
        stop_flag=Event(),
        epochs=5,
        normalize_metrics=lambda raw: normalize_metrics(raw, _to_float),
        to_float=_to_float,
        to_int=_to_int,
        epoch_callback=captured.append,
    )
    callback(_DummyTrainer())

    assert len(captured) == 1
    payload = captured[0]
    assert payload["step"] == 1
    assert payload["epoch"] == 1
    assert payload["total_steps"] == 5
    assert payload["eta_sec"] == 6
    assert payload["metrics"]["map50"] == pytest.approx(0.73)
    assert payload["metrics"]["precision"] == pytest.approx(0.8)
    assert payload["metrics"]["loss"] == pytest.approx(0.6)


def test_build_train_kwargs_for_deterministic_mode():
    kwargs = _build_train_kwargs(
        dataset_yaml=Path("/tmp/dataset.yaml"),
        epochs=10,
        batch=8,
        imgsz=640,
        patience=20,
        device="cuda:0",
        train_seed=123,
        deterministic=True,
        strong_deterministic=False,
        train_project_dir=Path("/tmp/project"),
    )
    assert kwargs["seed"] == 123
    assert kwargs["deterministic"] is True
    assert kwargs["workers"] == 2
    assert "amp" not in kwargs


def test_build_train_kwargs_for_strong_deterministic_mode():
    kwargs = _build_train_kwargs(
        dataset_yaml=Path("/tmp/dataset.yaml"),
        epochs=10,
        batch=8,
        imgsz=640,
        patience=20,
        device="cuda:0",
        train_seed=123,
        deterministic=True,
        strong_deterministic=True,
        train_project_dir=Path("/tmp/project"),
    )
    assert kwargs["seed"] == 123
    assert kwargs["deterministic"] is True
    assert kwargs["workers"] == 0
    assert kwargs["amp"] is False


def test_build_train_kwargs_for_non_deterministic_mode():
    kwargs = _build_train_kwargs(
        dataset_yaml=Path("/tmp/dataset.yaml"),
        epochs=10,
        batch=8,
        imgsz=640,
        patience=20,
        device="cuda:0",
        train_seed=123,
        deterministic=False,
        strong_deterministic=False,
        train_project_dir=Path("/tmp/project"),
    )
    assert kwargs["seed"] == 123
    assert kwargs["deterministic"] is False
    assert kwargs["workers"] == 2
    assert "amp" not in kwargs
    assert "cache" not in kwargs


def test_build_train_kwargs_enables_ram_cache_when_requested():
    kwargs = _build_train_kwargs(
        dataset_yaml=Path("/tmp/dataset.yaml"),
        epochs=10,
        batch=8,
        imgsz=640,
        patience=20,
        device="cuda:0",
        train_seed=123,
        deterministic=False,
        strong_deterministic=False,
        cache=True,
        train_project_dir=Path("/tmp/project"),
    )
    assert kwargs["workers"] == 2
    assert kwargs["cache"] == "ram"


def test_build_train_kwargs_arch_yaml_mode_sets_pretrained_false():
    kwargs = _build_train_kwargs(
        dataset_yaml=Path("/tmp/dataset.yaml"),
        epochs=10,
        batch=8,
        imgsz=640,
        patience=20,
        device="cuda:0",
        train_seed=123,
        deterministic=False,
        strong_deterministic=False,
        init_mode="arch_yaml_plus_weights",
        train_project_dir=Path("/tmp/project"),
    )
    assert kwargs["pretrained"] is False


class _FakeTensor:
    def __init__(self, *shape: int):
        self.shape = tuple(shape)


class _FakeModule:
    def __init__(self, state: dict[str, _FakeTensor]):
        self._state = dict(state)
        self.loaded_payload: dict[str, _FakeTensor] = {}
        self.loaded_strict: bool | None = None

    def state_dict(self):
        return dict(self._state)

    def load_state_dict(self, payload, strict=False):
        self.loaded_payload = dict(payload)
        self.loaded_strict = bool(strict)
        return object()


def test_build_training_model_arch_yaml_plus_weights_partially_loads_matching_keys():
    target_module = _FakeModule(
        {
            "model.0.conv.weight": _FakeTensor(32, 3, 3, 3),
            "model.1.bn.weight": _FakeTensor(32),
            "model.22.detect.weight": _FakeTensor(80, 32),
        }
    )
    source_module = _FakeModule(
        {
            "0.conv.weight": _FakeTensor(32, 3, 3, 3),
            "model.1.bn.weight": _FakeTensor(32),
            "cls.head.weight": _FakeTensor(1000, 128),
        }
    )

    class _FakeYOLO:
        def __init__(self, model_ref: str, task: str | None = None):
            self.model_ref = model_ref
            self.task = task
            if model_ref == "arch.yaml":
                self.model = target_module
            elif model_ref == "weights.pt":
                self.model = source_module
            else:
                raise RuntimeError(f"unexpected model_ref={model_ref}")

    model, summary = _build_training_model(
        YOLO=_FakeYOLO,
        base_model="weights.pt",
        yolo_task="detect",
        init_mode="arch_yaml_plus_weights",
        arch_yaml_ref="arch.yaml",
    )
    assert getattr(model, "model_ref", "") == "arch.yaml"
    assert summary["loaded_tensors"] == 2
    assert summary["shape_mismatch_tensors"] == 0
    assert summary["missing_in_target_tensors"] == 1
    assert target_module.loaded_strict is False
    assert set(target_module.loaded_payload.keys()) == {"model.0.conv.weight", "model.1.bn.weight"}


def test_build_training_model_arch_yaml_plus_weights_fails_when_no_tensor_matched():
    target_module = _FakeModule(
        {
            "model.0.conv.weight": _FakeTensor(32, 3, 3, 3),
        }
    )
    source_module = _FakeModule(
        {
            "cls.head.weight": _FakeTensor(1000, 128),
        }
    )

    class _FakeYOLO:
        def __init__(self, model_ref: str, task: str | None = None):
            self.model_ref = model_ref
            self.task = task
            self.model = target_module if model_ref == "arch.yaml" else source_module

    with pytest.raises(RuntimeError, match="loaded 0 tensors"):
        _build_training_model(
            YOLO=_FakeYOLO,
            base_model="weights.pt",
            yolo_task="detect",
            init_mode="arch_yaml_plus_weights",
            arch_yaml_ref="arch.yaml",
        )
