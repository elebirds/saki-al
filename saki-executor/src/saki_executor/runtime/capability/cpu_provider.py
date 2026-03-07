from __future__ import annotations

import os
import platform
import subprocess
from typing import Any


def _to_mb(total_bytes: int) -> int:
    if total_bytes <= 0:
        return 0
    return max(1, int(total_bytes // (1024 * 1024)))


def _detect_memory_mb() -> int:
    # Prefer portable sysconf first.
    try:
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        memory_mb = _to_mb(pages * page_size)
        if memory_mb > 0:
            return memory_mb
    except Exception:
        pass

    system = platform.system().lower()
    if system == "linux":
        # Fallback for some containers where sysconf is unavailable.
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if not line.startswith("MemTotal:"):
                        continue
                    parts = line.split()
                    if len(parts) >= 2:
                        kb = int(parts[1])
                        memory_mb = _to_mb(kb * 1024)
                        if memory_mb > 0:
                            return memory_mb
        except Exception:
            pass

    if system == "darwin":
        try:
            raw = subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            memory_mb = _to_mb(int(raw))
            if memory_mb > 0:
                return memory_mb
        except Exception:
            pass

    return 0


def probe_cpu(*, cpu_workers: int, memory_mb: int) -> dict[str, Any]:
    normalized_memory_mb = int(memory_mb or 0)
    if normalized_memory_mb <= 0:
        normalized_memory_mb = _detect_memory_mb()
    return {
        "cpu_workers": max(1, int(cpu_workers or (os.cpu_count() or 1))),
        "memory_mb": max(0, normalized_memory_mb),
        "platform": platform.system().lower(),
        "arch": platform.machine().lower(),
    }
