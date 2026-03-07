from __future__ import annotations

import threading
import time
from typing import Any

from saki_executor.runtime.capability.host_probe_service import HostProbeService
from saki_plugin_sdk import HostCapabilitySnapshot


class HostCapabilityCache:
    """Executor-scoped host capability cache.

    Probe is executed once at startup (or first access), then reused for all
    steps and heartbeat/register payloads. Call ``refresh`` explicitly to force
    a new probe.
    """

    def __init__(
        self,
        *,
        cpu_workers: int,
        memory_mb: int,
        probe_service: HostProbeService | None = None,
    ) -> None:
        self._cpu_workers = int(cpu_workers)
        self._memory_mb = int(memory_mb)
        self._probe_service = probe_service or HostProbeService()
        self._snapshot: HostCapabilitySnapshot | None = None
        self._last_probe_ts: int | None = None
        self._lock = threading.Lock()

    @property
    def last_probe_ts(self) -> int | None:
        return self._last_probe_ts

    def get_snapshot(self) -> HostCapabilitySnapshot:
        with self._lock:
            if self._snapshot is None:
                self._snapshot = self._probe_service.probe(
                    cpu_workers=self._cpu_workers,
                    memory_mb=self._memory_mb,
                )
                self._last_probe_ts = int(time.time())
            return self._snapshot

    def refresh(self) -> HostCapabilitySnapshot:
        with self._lock:
            self._snapshot = self._probe_service.probe(
                cpu_workers=self._cpu_workers,
                memory_mb=self._memory_mb,
            )
            self._last_probe_ts = int(time.time())
            return self._snapshot

    def get_resource_payload(self) -> dict[str, Any]:
        snapshot = self.get_snapshot()
        return self._probe_service.to_resource_payload(snapshot)
