from __future__ import annotations

import subprocess
from typing import Any


def probe_cuda_devices() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        cmd = ["nvidia-smi", "--query-gpu=index,name,memory.total,driver_version", "--format=csv,noheader,nounits"]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception as exc:
        return [], {"provider": "nvidia-smi", "error": str(exc)}

    return_code = int(result.returncode if result.returncode is not None else 1)
    if return_code != 0:
        return [], {
            "provider": "nvidia-smi",
            "error": (result.stderr or result.stdout or "").strip()[:300],
        }

    devices: list[dict[str, Any]] = []
    driver_version = ""
    for line in (result.stdout or "").splitlines():
        row = [item.strip() for item in line.split(",")]
        if len(row) < 4:
            continue
        gpu_id, name, memory_raw, driver = row[0], row[1], row[2], row[3]
        try:
            memory_mb = max(0, int(float(memory_raw)))
        except Exception:
            memory_mb = 0
        devices.append(
            {
                "id": str(gpu_id),
                "name": str(name),
                "memory_mb": memory_mb,
            }
        )
        if not driver_version:
            driver_version = str(driver).strip()

    return devices, {
        "provider": "nvidia-smi",
        "driver_version": driver_version,
    }
