from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from saki_plugin_sdk.capability_types import HostCapabilitySnapshot, RuntimeCapabilitySnapshot
from saki_plugin_sdk.device_binding import DeviceBinding
from saki_plugin_sdk.profile_spec import RuntimeProfileSpec


def normalize_backend_name(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"cpu", "cuda", "mps", "auto"}:
        return raw
    if raw.startswith("cuda:") or raw.isdigit() or "," in raw:
        return "cuda"
    return ""


@dataclass(frozen=True)
class DevicePriorityStrategy:
    priority_order: tuple[str, ...] = ("cuda", "mps", "cpu")

    def pick(self, allowed_backends: set[str]) -> str:
        for backend in self.priority_order:
            if backend in allowed_backends:
                return backend
        return ""


def _resolve_cuda_device_spec(requested_device_raw: str) -> str:
    raw = str(requested_device_raw or "").strip().lower()
    if raw.startswith("cuda:"):
        return raw
    if raw.isdigit():
        return f"cuda:{raw}"
    if "," in raw:
        return f"cuda:{raw.split(',')[0].strip()}"
    return "cuda:0"


def resolve_device_binding(
    *,
    requested_device: Any,
    host_capability: HostCapabilitySnapshot,
    runtime_capability: RuntimeCapabilitySnapshot,
    supported_backends: list[str],
    profile: RuntimeProfileSpec,
    allow_auto_fallback: bool,
    priority_strategy: DevicePriorityStrategy | None = None,
) -> DeviceBinding:
    strategy = priority_strategy or DevicePriorityStrategy()
    requested_raw = str(requested_device or "auto").strip().lower()
    requested_backend = normalize_backend_name(requested_raw) or "auto"

    host_backends = host_capability.available_backends()
    runtime_backends = runtime_capability.available_backends()
    plugin_supported = {
        backend
        for backend in (normalize_backend_name(item) for item in supported_backends)
        if backend and backend != "auto"
    } or {"cpu"}
    profile_allowed = {
        backend
        for backend in (normalize_backend_name(item) for item in profile.allowed_backends)
        if backend and backend != "auto"
    } or {"cpu"}

    allowed = host_backends & runtime_backends & plugin_supported & profile_allowed
    if not allowed:
        raise RuntimeError(
            "PROFILE_UNSATISFIED: no backend in host/runtime/plugin/profile intersection "
            f"host={sorted(host_backends)} runtime={sorted(runtime_backends)} "
            f"plugin={sorted(plugin_supported)} profile={sorted(profile_allowed)}"
        )

    fallback_applied = False
    if requested_backend != "auto":
        if requested_backend not in allowed:
            raise RuntimeError(
                "DEVICE_BINDING_CONFLICT: requested backend is not allowed "
                f"requested={requested_raw} allowed={sorted(allowed)}"
            )
        selected_backend = requested_backend
        reason = "explicit device request accepted"
    else:
        selected_backend = strategy.pick(allowed)
        if not selected_backend:
            raise RuntimeError(f"PROFILE_UNSATISFIED: allowed backend set is empty: {sorted(allowed)}")
        best_backend = strategy.pick(host_backends & runtime_backends & plugin_supported)
        fallback_applied = bool(best_backend and best_backend != selected_backend)
        reason = "auto mode selected by priority strategy"
        if not allow_auto_fallback and fallback_applied:
            raise RuntimeError(
                "DEVICE_BINDING_CONFLICT: auto fallback is disabled "
                f"selected={selected_backend} best={best_backend}"
            )

    if selected_backend == "cuda":
        device_spec = _resolve_cuda_device_spec(requested_raw)
        precision = "fp16"
    elif selected_backend == "mps":
        device_spec = "mps"
        precision = "fp16"
    else:
        device_spec = "cpu"
        precision = "fp32"

    return DeviceBinding(
        backend=selected_backend,
        device_spec=device_spec,
        precision=precision,
        profile_id=profile.id,
        reason=reason,
        fallback_applied=fallback_applied,
    )
