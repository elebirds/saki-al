from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from saki_plugin_sdk import (
    DevicePriorityStrategy,
    HostCapabilitySnapshot,
    RuntimeCapabilitySnapshot,
    RuntimeProfileSpec,
    resolve_device_binding,
)
from saki_plugin_sdk.device_binding import DeviceBinding


@dataclass(frozen=True)
class DeviceBindingResolver:
    priority_strategy: DevicePriorityStrategy = DevicePriorityStrategy()

    def resolve(
        self,
        *,
        requested_device: Any,
        host_capability: HostCapabilitySnapshot,
        runtime_capability: RuntimeCapabilitySnapshot,
        supported_backends: list[str],
        profile: RuntimeProfileSpec,
        allow_auto_fallback: bool,
    ) -> DeviceBinding:
        return resolve_device_binding(
            requested_device=requested_device,
            host_capability=host_capability,
            runtime_capability=runtime_capability,
            supported_backends=supported_backends,
            profile=profile,
            allow_auto_fallback=allow_auto_fallback,
            priority_strategy=self.priority_strategy,
        )
