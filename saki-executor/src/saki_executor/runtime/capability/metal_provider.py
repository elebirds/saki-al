from __future__ import annotations

import platform


def probe_metal_available() -> bool:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system != "darwin":
        return False
    return machine in {"arm64", "aarch64"}
