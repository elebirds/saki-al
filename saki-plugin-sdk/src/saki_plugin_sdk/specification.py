from __future__ import annotations

from typing import Any

from saki_plugin_sdk.capability_types import HostCapabilitySnapshot


class _SafeList(list):
    def includes(self, value: Any) -> bool:
        wanted = str(value or "").strip().lower()
        return any(str(item or "").strip().lower() == wanted for item in self)


class _HostNamespace:
    def __init__(self, snapshot: HostCapabilitySnapshot):
        self.platform = snapshot.platform
        self.arch = snapshot.arch
        self.metal_available = bool(snapshot.metal_available)
        self.cpu_workers = int(snapshot.cpu_workers)
        self.memory_mb = int(snapshot.memory_mb)
        self.backends = _SafeList(sorted(snapshot.available_backends()))
        self.gpu_count = len(snapshot.gpus)


def evaluate_profile_spec(expr: str, *, host_capability: HostCapabilitySnapshot) -> bool:
    expression = str(expr or "").strip()
    if not expression:
        return True
    expression = expression.replace("===", "==").replace("!==", "!=")
    expression = expression.replace("&&", " and ").replace("||", " or ")
    context = {
        "host": _HostNamespace(host_capability),
    }
    try:
        return bool(eval(expression, {"__builtins__": {}}, context))
    except Exception:
        return False
