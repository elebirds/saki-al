from __future__ import annotations

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
