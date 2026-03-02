from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from saki_plugin_sdk.base import TrainArtifact, TrainOutput
from saki_plugin_sdk.types import StepRuntimeContext

WORKER_EVENT_TOPICS = ("progress", "log", "metric", "status", "artifact", "worker")
WORKER_PROTOCOL_VERSION = 2


@dataclass(frozen=True)
class WorkerCommandEnvelope:
    request_id: str
    action: str
    step_id: str
    protocol_version: int = WORKER_PROTOCOL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "action": self.action,
            "step_id": self.step_id,
            "protocol_version": self.protocol_version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkerCommandEnvelope":
        return cls(
            request_id=str(payload.get("request_id") or ""),
            action=str(payload.get("action") or ""),
            step_id=str(payload.get("step_id") or ""),
            protocol_version=int(payload.get("protocol_version") or 1),
        )


@dataclass(frozen=True)
class WorkerEventEnvelope:
    event_type: str
    step_id: str
    ts: int
    request_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "step_id": self.step_id,
            "ts": self.ts,
            "request_id": self.request_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkerEventEnvelope":
        return cls(
            event_type=str(payload.get("event_type") or ""),
            step_id=str(payload.get("step_id") or ""),
            ts=int(payload.get("ts") or 0),
            request_id=str(payload.get("request_id") or ""),
        )


@dataclass(frozen=True)
class WorkerReplyEnvelope:
    request_id: str
    ok: bool
    error_code: str
    error_message: str
    result_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "ok": self.ok,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "result_path": self.result_path,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkerReplyEnvelope":
        return cls(
            request_id=str(payload.get("request_id") or ""),
            ok=bool(payload.get("ok")),
            error_code=str(payload.get("error_code") or ""),
            error_message=str(payload.get("error_message") or ""),
            result_path=str(payload.get("result_path") or ""),
        )


def build_command_payload(
    *,
    envelope: WorkerCommandEnvelope,
    payload: dict[str, Any] | None = None,
    context: StepRuntimeContext | dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = dict(payload or {})
    if context is not None:
        body["context"] = context.to_dict() if isinstance(context, StepRuntimeContext) else dict(context)
    return {
        "envelope": envelope.to_dict(),
        "payload": body,
    }


def parse_command_payload(raw: dict[str, Any]) -> tuple[WorkerCommandEnvelope, dict[str, Any]]:
    envelope_payload = raw.get("envelope")
    payload = raw.get("payload")
    if not isinstance(envelope_payload, dict):
        raise ValueError("missing command envelope")
    if not isinstance(payload, dict):
        payload = {}
    envelope = WorkerCommandEnvelope.from_dict(envelope_payload)
    if envelope.protocol_version != WORKER_PROTOCOL_VERSION:
        raise ValueError(
            f"unsupported protocol_version={envelope.protocol_version}, expected={WORKER_PROTOCOL_VERSION}"
        )
    return envelope, payload


def parse_runtime_context(payload: dict[str, Any]) -> StepRuntimeContext:
    context_raw = payload.get("context")
    if not isinstance(context_raw, dict):
        raise ValueError("missing runtime context")
    return StepRuntimeContext.from_dict(context_raw)


def build_event_frames(
    *,
    topic: str,
    envelope: WorkerEventEnvelope,
    payload: dict[str, Any] | None = None,
    payload_bytes: bytes | None = None,
) -> list[bytes]:
    topic_raw = str(topic or "").strip()
    if not topic_raw:
        raise ValueError("topic is required")
    if payload_bytes is not None and payload is not None:
        raise ValueError("payload and payload_bytes are mutually exclusive")
    body = payload_bytes if payload_bytes is not None else json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    return [
        topic_raw.encode("utf-8"),
        json.dumps(envelope.to_dict(), ensure_ascii=False).encode("utf-8"),
        body,
    ]


def parse_event_frames(frames: list[bytes] | tuple[bytes, ...]) -> tuple[str, WorkerEventEnvelope, dict[str, Any] | bytes]:
    if len(frames) != 3:
        raise ValueError("event frame count must be 3")
    topic = frames[0].decode("utf-8").strip()
    envelope_raw = json.loads(frames[1].decode("utf-8"))
    if not isinstance(envelope_raw, dict):
        raise ValueError("event envelope must be an object")
    envelope = WorkerEventEnvelope.from_dict(envelope_raw)
    try:
        payload = json.loads(frames[2].decode("utf-8"))
        if not isinstance(payload, dict):
            payload = {"value": payload}
        return topic, envelope, payload
    except Exception:
        return topic, envelope, bytes(frames[2])


def now_ts() -> int:
    return int(time.time())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def train_output_to_dict(output: TrainOutput) -> dict[str, Any]:
    return {
        "metrics": output.metrics,
        "artifacts": [
            {
                "kind": artifact.kind,
                "name": artifact.name,
                "path": str(artifact.path),
                "content_type": artifact.content_type,
                "meta": artifact.meta or {},
                "required": bool(artifact.required),
            }
            for artifact in output.artifacts
        ],
    }


def train_output_from_dict(payload: dict[str, Any]) -> TrainOutput:
    metrics_raw = payload.get("metrics")
    artifacts_raw = payload.get("artifacts")
    metrics = dict(metrics_raw) if isinstance(metrics_raw, dict) else {}
    rows = artifacts_raw if isinstance(artifacts_raw, list) else []
    artifacts: list[TrainArtifact] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        artifacts.append(
            TrainArtifact(
                kind=str(item.get("kind") or ""),
                name=str(item.get("name") or ""),
                path=Path(str(item.get("path") or "")),
                content_type=str(item.get("content_type") or "application/octet-stream"),
                meta=dict(item.get("meta") or {}),
                required=bool(item.get("required")),
            )
        )
    return TrainOutput(metrics=metrics, artifacts=artifacts)
