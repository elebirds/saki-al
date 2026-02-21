from __future__ import annotations

import hashlib
import os
import traceback
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .ipc import IPCConfig, KernelIPCClient

_FORBIDDEN_ENV_PREFIXES = ("MINIO_", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")


class KernelBase(ABC):
    """Python Kernel 基类。

    提供：
    1. IPC 通讯封装（log/progress/metric）
    2. 统一异常捕获上报
    3. `USE_CPU_FOR_LOSS` 约定读取
    """

    def __init__(
        self,
        *,
        control_uri: str,
        event_uri: str,
        workspace: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.payload = payload or {}
        self.ipc = KernelIPCClient(IPCConfig(control_uri=control_uri, event_uri=event_uri))
        self.use_cpu_for_loss = str(os.getenv("USE_CPU_FOR_LOSS", "false")).strip().lower() == "true"

    def _guard_environment(self) -> None:
        for key in os.environ:
            upper = key.strip().upper()
            if upper.startswith(_FORBIDDEN_ENV_PREFIXES):
                raise RuntimeError(f"forbidden storage credential in kernel env: {key}")

    def log(self, level: str, message: str) -> None:
        self.ipc.emit_log(level=level, message=message)

    def progress(self, *, epoch: int, step: int, total_steps: int, eta_sec: int) -> None:
        self.ipc.emit_progress(epoch=epoch, step=step, total_steps=total_steps, eta_sec=eta_sec)

    def metric(self, *, step: int, epoch: int, metrics: dict[str, float]) -> None:
        self.ipc.emit_metric(step=step, epoch=epoch, metrics=metrics)

    def artifact_local_ready(self, *, file_path: str, kind: str, required: bool = True) -> None:
        abs_path = Path(file_path).resolve()
        rel_path = str(abs_path.relative_to(self.workspace))
        digest = hashlib.sha256(abs_path.read_bytes()).hexdigest()
        self.ipc.emit_artifact_local_ready(
            relative_path=rel_path,
            size_bytes=abs_path.stat().st_size,
            sha256=digest,
            kind=kind,
            required=required,
        )

    def run(self) -> int:
        try:
            self._guard_environment()
            self.workspace.mkdir(parents=True, exist_ok=True)
            self.log("INFO", f"kernel start use_cpu_for_loss={self.use_cpu_for_loss}")
            self.execute()
            self.log("INFO", "kernel finished")
            return 0
        except Exception as exc:  # noqa: BLE001
            self.log("ERROR", f"kernel failed: {exc}")
            self.log("ERROR", traceback.format_exc())
            return 1
        finally:
            self.ipc.close()

    @abstractmethod
    def execute(self) -> None:
        """子类实现纯 AI 逻辑。"""
