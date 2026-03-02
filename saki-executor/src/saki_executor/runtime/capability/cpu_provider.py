from __future__ import annotations

import os
import platform
from typing import Any


def probe_cpu(*, cpu_workers: int, memory_mb: int) -> dict[str, Any]:
    return {
        "cpu_workers": max(1, int(cpu_workers or (os.cpu_count() or 1))),
        "memory_mb": max(0, int(memory_mb or 0)),
        "platform": platform.system().lower(),
        "arch": platform.machine().lower(),
    }
