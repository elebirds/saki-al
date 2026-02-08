from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from saki_executor.jobs.state import JobStatus
from saki_executor.sdk.reporter import JobReporter

PushEventFn = Callable[[dict[str, Any]], Awaitable[None]]


class JobEventEmitter:
    def __init__(
        self,
        *,
        reporter: JobReporter,
        stop_event: asyncio.Event,
        push_event: PushEventFn,
    ) -> None:
        self._reporter = reporter
        self._stop_event = stop_event
        self._push_event = push_event

    async def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._stop_event.is_set():
            raise asyncio.CancelledError("job stop requested")
        event = self._build_event(event_type, payload)
        await self._push_event(event)

    async def emit_status(self, status: JobStatus, reason: str) -> None:
        await self.emit("status", {"status": status.value, "reason": reason})

    def _build_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if event_type == "log":
            return self._reporter.log(
                level=str(payload.get("level", "INFO")),
                message=str(payload.get("message", "")),
            )
        if event_type == "progress":
            return self._reporter.progress(
                epoch=int(payload.get("epoch", 0)),
                step=int(payload.get("step", 0)),
                total_steps=int(payload.get("total_steps", 0)),
                eta_sec=payload.get("eta_sec"),
            )
        if event_type == "metric":
            metrics = payload.get("metrics") or {}
            return self._reporter.metric(
                step=int(payload.get("step", 0)),
                epoch=payload.get("epoch"),
                metrics={str(k): float(v) for k, v in metrics.items()},
            )
        if event_type == "artifact":
            return self._reporter.log(
                "WARN",
                "plugin artifact event is ignored; "
                + f"artifact_name={str(payload.get('name', ''))}",
            )
        if event_type == "status":
            return self._reporter.status(
                status=str(payload.get("status", JobStatus.RUNNING.value)),
                reason=payload.get("reason"),
            )
        return self._reporter.log("WARN", f"unknown event type: {event_type}")

