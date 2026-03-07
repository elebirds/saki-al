from __future__ import annotations

from typing import Any

from saki_executor.runtime.capability.cpu_provider import probe_cpu
from saki_executor.runtime.capability.cuda_nvml_provider import probe_cuda_devices
from saki_executor.runtime.capability.metal_provider import probe_metal_available
from saki_plugin_sdk import GpuDeviceCapability, HostCapabilitySnapshot


class HostProbeService:
    def probe(self, *, cpu_workers: int, memory_mb: int) -> HostCapabilitySnapshot:
        cpu_payload = probe_cpu(cpu_workers=cpu_workers, memory_mb=memory_mb)
        gpus_raw, driver_info = probe_cuda_devices()
        gpus = [GpuDeviceCapability.from_dict(item) for item in gpus_raw]
        return HostCapabilitySnapshot(
            cpu_workers=int(cpu_payload.get("cpu_workers") or 1),
            memory_mb=int(cpu_payload.get("memory_mb") or 0),
            gpus=gpus,
            metal_available=probe_metal_available(),
            platform=str(cpu_payload.get("platform") or "").strip().lower(),
            arch=str(cpu_payload.get("arch") or "").strip().lower(),
            driver_info=dict(driver_info or {}),
        )

    @staticmethod
    def to_resource_payload(snapshot: HostCapabilitySnapshot) -> dict[str, Any]:
        gpu_device_ids = []
        for item in snapshot.gpus:
            try:
                gpu_device_ids.append(int(item.id))
            except Exception:
                continue
        accelerators: list[dict[str, Any]] = []
        if snapshot.gpus:
            accelerators.append(
                {
                    "type": "cuda",
                    "available": True,
                    "device_count": len(snapshot.gpus),
                    "device_ids": [item.id for item in snapshot.gpus],
                }
            )
        accelerators.append(
            {
                "type": "mps",
                "available": bool(snapshot.metal_available),
                "device_count": 1 if snapshot.metal_available else 0,
                "device_ids": ["mps"] if snapshot.metal_available else [],
            }
        )
        accelerators.append(
            {
                "type": "cpu",
                "available": True,
                "device_count": 1,
                "device_ids": ["cpu"],
            }
        )
        return {
            "gpu_count": len(snapshot.gpus),
            "gpu_device_ids": gpu_device_ids,
            "cpu_workers": int(snapshot.cpu_workers),
            "memory_mb": int(snapshot.memory_mb),
            "accelerators": accelerators,
            "host_capability": snapshot.to_dict(),
        }
