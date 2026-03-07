from __future__ import annotations

from pathlib import Path

from saki_executor.agent.client import AgentClient
from saki_executor.cache.asset_cache import AssetCache
from saki_executor.plugins.registry import PluginRegistry
from saki_executor.runtime.capability.host_capability_cache import HostCapabilityCache
from saki_executor.steps.manager import TaskManager
from saki_plugin_sdk import HostCapabilitySnapshot


class _FakeProbeService:
    def __init__(self) -> None:
        self.probe_calls = 0

    def probe(self, *, cpu_workers: int, memory_mb: int) -> HostCapabilitySnapshot:
        self.probe_calls += 1
        return HostCapabilitySnapshot.from_dict(
            {
                "cpu_workers": int(cpu_workers),
                "memory_mb": int(memory_mb),
                "gpus": [{"id": "0"}] if self.probe_calls >= 2 else [],
                "metal_available": False,
                "platform": "darwin",
                "arch": "arm64",
                "driver_info": {},
            }
        )

    @staticmethod
    def to_resource_payload(snapshot: HostCapabilitySnapshot) -> dict:
        return {
            "gpu_count": len(snapshot.gpus),
            "gpu_device_ids": [0] if snapshot.gpus else [],
            "cpu_workers": int(snapshot.cpu_workers),
            "memory_mb": int(snapshot.memory_mb),
            "accelerators": [
                {
                    "type": "cuda",
                    "available": bool(snapshot.gpus),
                    "device_count": len(snapshot.gpus),
                    "device_ids": [item.id for item in snapshot.gpus],
                },
                {"type": "cpu", "available": True, "device_count": 1, "device_ids": ["cpu"]},
            ],
            "host_capability": snapshot.to_dict(),
        }


def _build_manager(tmp_path: Path, *, cache: HostCapabilityCache) -> TaskManager:
    registry = PluginRegistry()
    asset_cache = AssetCache(root_dir=str(tmp_path / "cache"), max_bytes=1024 * 1024)
    return TaskManager(
        runs_dir=str(tmp_path / "runs"),
        cache=asset_cache,
        plugin_registry=registry,
        host_capability_cache=cache,
    )


def test_host_capability_cache_reuses_snapshot_until_manual_refresh(tmp_path: Path):
    probe = _FakeProbeService()
    capability_cache = HostCapabilityCache(
        cpu_workers=4,
        memory_mb=2048,
        probe_service=probe,  # type: ignore[arg-type]
    )
    manager = _build_manager(tmp_path, cache=capability_cache)
    client = AgentClient(plugin_registry=manager.plugin_registry, task_manager=manager)

    first = client._resource_payload()  # noqa: SLF001
    second = client._resource_payload()  # noqa: SLF001
    assert probe.probe_calls == 1
    assert first["gpu_count"] == 0
    assert second["gpu_count"] == 0

    manager.refresh_host_capability()
    third = client._resource_payload()  # noqa: SLF001
    assert probe.probe_calls == 2
    assert third["gpu_count"] == 1
