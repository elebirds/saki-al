from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from saki_plugin_sdk.capability_types import HostCapabilitySnapshot, RuntimeCapabilitySnapshot
from saki_plugin_sdk.device_binding import DeviceBinding
from saki_plugin_sdk.types import TaskRuntimeContext


@dataclass(frozen=True)
class ExecutionBindingContext:
    task_context: TaskRuntimeContext
    host_capability: HostCapabilitySnapshot
    runtime_capability: RuntimeCapabilitySnapshot
    device_binding: DeviceBinding
    profile_id: str

    def __getattr__(self, item: str) -> Any:
        return getattr(self.task_context, item)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_context": self.task_context.to_dict(),
            "host_capability": self.host_capability.to_dict(),
            "runtime_capability": self.runtime_capability.to_dict(),
            "device_binding": self.device_binding.to_dict(),
            "profile_id": str(self.profile_id or "").strip(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExecutionBindingContext":
        task_context_raw = payload.get("task_context")
        if not isinstance(task_context_raw, dict):
            raise ValueError("execution binding context missing task_context")
        host_raw = payload.get("host_capability")
        if not isinstance(host_raw, dict):
            raise ValueError("execution binding context missing host_capability")
        runtime_raw = payload.get("runtime_capability")
        if not isinstance(runtime_raw, dict):
            raise ValueError("execution binding context missing runtime_capability")
        binding_raw = payload.get("device_binding")
        if not isinstance(binding_raw, dict):
            raise ValueError("execution binding context missing device_binding")
        return cls(
            task_context=TaskRuntimeContext.from_dict(task_context_raw),
            host_capability=HostCapabilitySnapshot.from_dict(host_raw),
            runtime_capability=RuntimeCapabilitySnapshot.from_dict(runtime_raw),
            device_binding=DeviceBinding.from_dict(binding_raw),
            profile_id=str(payload.get("profile_id") or "").strip(),
        )
