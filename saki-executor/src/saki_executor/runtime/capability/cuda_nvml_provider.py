from __future__ import annotations

import re
import subprocess
from typing import Any


_RICH_QUERY_FIELDS = [
    "index",
    "name",
    "memory.total",
    "driver_version",
    "compute_cap",
    "multiprocessor_count",
    "clocks.max.sm",
]
_BASIC_QUERY_FIELDS = ["index", "name", "memory.total", "driver_version"]


def _to_int(value: str) -> int | None:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return None


def _to_float(value: str) -> float | None:
    try:
        return float(str(value).strip())
    except Exception:
        return None


def _parse_compute_capability(value: str) -> tuple[str, int | None, int | None]:
    raw = str(value or "").strip()
    if not raw:
        return "", None, None
    matched = re.match(r"^\s*(\d+)(?:\.(\d+))?\s*$", raw)
    if not matched:
        return raw, None, None
    major = int(matched.group(1))
    minor = int(matched.group(2) or 0)
    return f"{major}.{minor}", major, minor


def _cores_per_sm(major: int, minor: int) -> int | None:
    if major == 2:
        return 32 if minor == 1 else 48
    if major == 3:
        return 192
    if major == 5:
        return 128
    if major == 6:
        return 64 if minor == 0 else 128
    if major == 7:
        return 64
    if major == 8:
        if minor == 0:
            return 64
        return 128
    if major >= 9:
        return 128
    return None


def _estimate_fp32_tflops(*, compute_major: int | None, compute_minor: int | None, sm_count: int | None, sm_clock_mhz: float | None) -> float | None:
    if compute_major is None or compute_minor is None or sm_count is None or sm_clock_mhz is None:
        return None
    cores_per_sm = _cores_per_sm(compute_major, compute_minor)
    if cores_per_sm is None:
        return None
    if sm_count <= 0 or sm_clock_mhz <= 0:
        return None
    total_cuda_cores = sm_count * cores_per_sm
    tflops = (float(total_cuda_cores) * 2.0 * sm_clock_mhz) / 1_000_000.0
    return round(tflops, 3)


def _query_cuda_version() -> str:
    try:
        result = subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return ""
    if int(result.returncode if result.returncode is not None else 1) != 0:
        return ""
    output = str(result.stdout or "")
    matched = re.search(r"CUDA Version:\s*([0-9.]+)", output)
    if not matched:
        return ""
    return str(matched.group(1) or "").strip()


def _run_query(fields: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [
        "nvidia-smi",
        f"--query-gpu={','.join(fields)}",
        "--format=csv,noheader,nounits",
    ]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def probe_cuda_devices() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    query_fields = _RICH_QUERY_FIELDS
    try:
        result = _run_query(_RICH_QUERY_FIELDS)
    except Exception as exc:
        return [], {"provider": "nvidia-smi", "error": str(exc)}

    return_code = int(result.returncode if result.returncode is not None else 1)
    if return_code != 0:
        try:
            query_fields = _BASIC_QUERY_FIELDS
            result = _run_query(_BASIC_QUERY_FIELDS)
        except Exception as exc:
            return [], {
                "provider": "nvidia-smi",
                "error": str(exc),
            }
        return_code = int(result.returncode if result.returncode is not None else 1)
        if return_code != 0:
            return [], {
                "provider": "nvidia-smi",
                "error": (result.stderr or result.stdout or "").strip()[:300],
            }

    devices: list[dict[str, Any]] = []
    driver_version = ""
    cuda_version = _query_cuda_version()
    for line in (result.stdout or "").splitlines():
        row = [item.strip() for item in line.split(",")]
        if len(row) < 4:
            continue
        gpu_id, name, memory_raw, driver = row[0], row[1], row[2], row[3]
        memory_mb = _to_int(memory_raw)
        if memory_mb is None:
            memory_mb = 0
        memory_mb = max(0, memory_mb)
        compute_capability = ""
        compute_major: int | None = None
        compute_minor: int | None = None
        multiprocessor_count: int | None = None
        sm_clock_mhz: float | None = None
        if len(query_fields) >= len(_RICH_QUERY_FIELDS) and len(row) >= 7:
            compute_capability, compute_major, compute_minor = _parse_compute_capability(row[4])
            multiprocessor_count = _to_int(row[5])
            sm_clock_mhz = _to_float(row[6])
        fp32_tflops = _estimate_fp32_tflops(
            compute_major=compute_major,
            compute_minor=compute_minor,
            sm_count=multiprocessor_count,
            sm_clock_mhz=sm_clock_mhz,
        )
        devices.append(
            {
                "id": str(gpu_id),
                "name": str(name),
                "memory_mb": memory_mb,
                "compute_capability": compute_capability,
                "fp32_tflops": fp32_tflops,
            }
        )
        if not driver_version:
            driver_version = str(driver).strip()

    return devices, {
        "provider": "nvidia-smi",
        "driver_version": driver_version,
        "cuda_version": cuda_version,
    }
