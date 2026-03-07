from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from loguru import logger

from saki_executor.steps.state import TaskStatus
from saki_plugin_sdk import TaskReporter

PushEventFn = Callable[[dict[str, Any]], Awaitable[None]]


class TaskEventEmitter:
    def __init__(
        self,
        *,
        reporter: TaskReporter,
        stop_event: asyncio.Event,
        push_event: PushEventFn,
    ) -> None:
        self._reporter = reporter
        self._stop_event = stop_event
        self._push_event = push_event

    async def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._stop_event.is_set():
            raise asyncio.CancelledError("任务已请求停止")
        event = self._build_event(event_type, payload)
        await self._push_event(event)

    async def emit_status(self, status: TaskStatus, reason: str) -> None:
        await self.emit("status", {"status": status.value, "reason": reason})

    async def emit_stage_start(self, *, stage: str, message: str) -> None:
        await self.emit(
            "log",
            {
                "level": "INFO",
                "message": message,
                "message_key": "step.stage",
                "message_args": {"stage": stage, "phase": "start"},
                "meta": {"stage": stage, "phase": "start"},
            },
        )

    async def emit_stage_success(self, *, stage: str, message: str) -> None:
        await self.emit(
            "log",
            {
                "level": "INFO",
                "message": message,
                "message_key": "step.stage",
                "message_args": {"stage": stage, "phase": "success"},
                "meta": {"stage": stage, "phase": "success"},
            },
        )

    async def emit_stage_fail(self, *, stage: str, error_code: str, message: str) -> None:
        await self.emit(
            "log",
            {
                "level": "ERROR",
                "message": f"[{error_code}] {message} (stage={stage})",
                "message_key": "step.stage",
                "message_args": {
                    "stage": stage,
                    "phase": "fail",
                    "error_code": error_code,
                },
                "meta": {
                    "stage": stage,
                    "phase": "fail",
                    "error_code": error_code,
                },
            },
        )

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
            normalized_metrics = {str(k): float(v) for k, v in metrics.items()}
            step_value = int(payload.get("step", 0))
            epoch_raw = payload.get("epoch")
            epoch_text = f" epoch={int(epoch_raw)}" if epoch_raw is not None else ""
            if normalized_metrics:
                preview = ", ".join(
                    f"{name}={value:.6f}".rstrip("0").rstrip(".")
                    for name, value in sorted(normalized_metrics.items(), key=lambda item: item[0])
                )
            else:
                preview = "空"
            logger.info("指标事件 step={}{} {}", step_value, epoch_text, preview)
            return self._reporter.metric(
                step=step_value,
                epoch=payload.get("epoch"),
                metrics=normalized_metrics,
            )
        if event_type == "artifact":
            return self._reporter.log(
                "WARN",
                "插件 artifact 事件已忽略; " + f"artifact_name={str(payload.get('name', ''))}",
            )
        if event_type == "status":
            return self._reporter.status(
                status=str(payload.get("status", TaskStatus.RUNNING.value)),
                reason=payload.get("reason"),
            )
        return self._reporter.log("WARN", f"未知事件类型: {event_type}")
