from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExecuteRequest:
    request_id: str
    task_id: str
    action: str
    payload: bytes

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "task_id": self.task_id,
            "action": self.action,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class WorkerEvent:
    request_id: str
    task_id: str
    event_type: str
    payload: bytes

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "task_id": self.task_id,
            "event_type": self.event_type,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class ExecuteResult:
    request_id: str
    ok: bool
    error_code: str = ""
    error_message: str = ""
    payload: bytes = b""

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "ok": self.ok,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "payload": self.payload,
        }
