from __future__ import annotations

from saki_executor.runtime.capability import cpu_provider


def test_probe_cpu_uses_explicit_memory_mb(monkeypatch) -> None:
    monkeypatch.setattr(cpu_provider, "_detect_memory_mb", lambda: 32768)

    payload = cpu_provider.probe_cpu(cpu_workers=4, memory_mb=8192)

    assert payload["cpu_workers"] == 4
    assert payload["memory_mb"] == 8192


def test_probe_cpu_auto_detects_memory_when_unset(monkeypatch) -> None:
    monkeypatch.setattr(cpu_provider, "_detect_memory_mb", lambda: 24576)

    payload = cpu_provider.probe_cpu(cpu_workers=4, memory_mb=0)

    assert payload["memory_mb"] == 24576


def test_probe_cpu_keeps_zero_when_detection_fails(monkeypatch) -> None:
    monkeypatch.setattr(cpu_provider, "_detect_memory_mb", lambda: 0)

    payload = cpu_provider.probe_cpu(cpu_workers=4, memory_mb=0)

    assert payload["memory_mb"] == 0
