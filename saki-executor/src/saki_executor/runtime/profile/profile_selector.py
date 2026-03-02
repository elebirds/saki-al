from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from saki_plugin_sdk import HostCapabilitySnapshot, RuntimeProfileSpec, evaluate_profile_spec, normalize_backend_name


@dataclass(frozen=True)
class ProfileSelectorStrategy:
    mode: str = "performance_first"

    def select(
        self,
        *,
        profiles: list[RuntimeProfileSpec],
        host_capability: HostCapabilitySnapshot,
        requested_device: Any,
    ) -> RuntimeProfileSpec:
        if not profiles:
            raise RuntimeError("PROFILE_UNSATISFIED: runtime_profiles is empty")
        requested_backend = normalize_backend_name(requested_device) or "auto"

        candidates: list[RuntimeProfileSpec] = []
        for profile in profiles:
            if not evaluate_profile_spec(profile.when, host_capability=host_capability):
                continue
            allowed = {normalize_backend_name(item) for item in profile.allowed_backends}
            if requested_backend != "auto" and requested_backend not in allowed:
                continue
            candidates.append(profile)
        if not candidates:
            raise RuntimeError(
                "PROFILE_UNSATISFIED: no runtime profile matches host capability "
                f"requested={requested_device}"
            )
        # Currently only performance-first strategy is implemented:
        # lower priority number means higher priority.
        return sorted(candidates, key=lambda item: (int(item.priority), item.id))[0]
