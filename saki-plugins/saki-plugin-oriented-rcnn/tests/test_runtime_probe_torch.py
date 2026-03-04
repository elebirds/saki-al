from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest

import saki_plugin_oriented_rcnn.runtime_probe_torch as runtime_probe


def test_probe_runtime_capability_success_with_mm_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_torch = SimpleNamespace(
        __version__="2.10.0+cu128",
        cuda=SimpleNamespace(is_available=lambda: True, device_count=lambda: 1),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(runtime_probe, "_ensure_mm_runtime_dependencies", lambda: None)

    snapshot = runtime_probe.probe_torch_runtime_capability()
    assert snapshot.framework == "torch"
    assert "cuda" in snapshot.backends
    assert snapshot.backend_details.get("cuda_device_count") == 1


def test_probe_runtime_capability_raises_when_mmcv_ext_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_torch = SimpleNamespace(
        __version__="2.10.0+cu128",
        cuda=SimpleNamespace(is_available=lambda: False, device_count=lambda: 0),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    def _raise() -> None:
        raise RuntimeError("runtime dependency check failed: missing mmcv._ext")

    monkeypatch.setattr(runtime_probe, "_ensure_mm_runtime_dependencies", _raise)

    # 关键验证：依赖缺失要在 probing 阶段直接失败，而不是拖到 train 阶段。
    with pytest.raises(RuntimeError, match="mmcv\\._ext"):
        runtime_probe.probe_torch_runtime_capability()


def test_mmcv_ext_missing_error_contains_prebuilt_wheel_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_torch = SimpleNamespace(
        __version__="2.10.0+cu128",
        cuda=SimpleNamespace(is_available=lambda: True, device_count=lambda: 1),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    real_import_module = importlib.import_module
    real_find_spec = runtime_probe.importlib.util.find_spec

    def _fake_import_module(name: str):
        if name == "mmengine":
            return SimpleNamespace()
        return real_import_module(name)

    def _fake_find_spec(name: str):
        if name == "mmcv":
            return object()
        if name == "mmcv._ext":
            return None
        return real_find_spec(name)

    monkeypatch.setattr(runtime_probe.importlib, "import_module", _fake_import_module)
    monkeypatch.setattr(runtime_probe.importlib.util, "find_spec", _fake_find_spec)

    with pytest.raises(RuntimeError) as exc_info:
        runtime_probe.probe_torch_runtime_capability()
    message = str(exc_info.value)
    assert "mmcv._ext" in message
    assert "prebuilt onedl-mmcv wheel" in message
