from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import zmq


@dataclass(slots=True)
class IPCConfig:
    control_uri: str
    event_uri: str


class KernelIPCClient:
    """Kernel 侧 IPC 客户端。

    约束：
    1. 仅使用 IPC（Unix Domain Socket），不支持 TCP。
    2. 控制通道建议 DEALER，事件通道使用 PUSH。
    """

    def __init__(self, config: IPCConfig) -> None:
        if not config.control_uri.startswith("ipc://"):
            raise ValueError("control_uri must start with ipc://")
        if not config.event_uri.startswith("ipc://"):
            raise ValueError("event_uri must start with ipc://")
        self._config = config
        self._ctx = zmq.Context.instance()
        self._event = self._ctx.socket(zmq.PUSH)
        self._event.connect(config.event_uri)

    def close(self) -> None:
        self._event.close(linger=50)

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        envelope = {
            "event_type": str(event_type),
            "ts_ms": int(time.time() * 1000),
            "payload": payload,
        }
        self._event.send_json(envelope)

    def emit_metric(self, step: int, epoch: int, metrics: dict[str, float]) -> None:
        self.emit("metric", {"step": int(step), "epoch": int(epoch), "metrics": {k: float(v) for k, v in metrics.items()}})

    def emit_progress(self, epoch: int, step: int, total_steps: int, eta_sec: int) -> None:
        self.emit(
            "progress",
            {
                "epoch": int(epoch),
                "step": int(step),
                "total_steps": int(total_steps),
                "eta_sec": int(eta_sec),
            },
        )

    def emit_log(self, level: str, message: str) -> None:
        self.emit("log", {"level": str(level), "message": str(message)})

    def emit_artifact_local_ready(
        self,
        *,
        relative_path: str,
        size_bytes: int,
        sha256: str,
        kind: str,
        required: bool,
    ) -> None:
        self.emit(
            "artifact_local_ready",
            {
                "relative_path": str(relative_path),
                "size_bytes": int(size_bytes),
                "sha256": str(sha256),
                "kind": str(kind),
                "required": bool(required),
            },
        )

    def emit_raw(self, raw_json: str) -> None:
        self._event.send_json(json.loads(raw_json))
