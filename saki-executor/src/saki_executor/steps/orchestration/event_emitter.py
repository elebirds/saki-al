from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from saki_executor.steps.state import StepStatus
from saki_plugin_sdk import StepReporter

PushEventFn = Callable[[dict[str, Any]], Awaitable[None]]


class StepEventEmitter:
    def __init__(
        self,
        *,
        reporter: StepReporter,
        stop_event: asyncio.Event,
        push_event: PushEventFn,
    ) -> None:
        self._reporter = reporter
        self._stop_event = stop_event
        self._push_event = push_event

    async def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._stop_event.is_set():
            raise asyncio.CancelledError("task stop requested")
        event = self._build_event(event_type, payload)
        await self._push_event(event)

    async def emit_status(self, status: StepStatus, reason: str) -> None:
        await self.emit("status", {"status": status.value, "reason": reason})

    def _build_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if event_type == "log":
            return self._reporter.log(
                level=str(payload.get("level", "INFO")),
                message=str(payload.get("message", "")),
                raw_message=(
                    str(payload.get("raw_message"))
                    if payload.get("raw_message") is not None
                    else None
                ),
                message_key=(
                    str(payload.get("message_key"))
                    if payload.get("message_key") is not None
                    else None
                ),
                message_args=(
                    payload.get("message_args")
                    if isinstance(payload.get("message_args"), dict)
                    else None
                ),
                meta=(
                    payload.get("meta")
                    if isinstance(payload.get("meta"), dict)
                    else None
                ),
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
                "plugin artifact event is ignored; " + f"artifact_name={str(payload.get('name', ''))}",
            )
        if event_type == "status":
            return self._reporter.status(
                status=str(payload.get("status", StepStatus.RUNNING.value)),
                reason=payload.get("reason"),
            )
        return self._reporter.log("WARN", f"unknown event type: {event_type}")
