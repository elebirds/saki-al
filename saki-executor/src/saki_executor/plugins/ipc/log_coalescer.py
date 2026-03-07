from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
import re
import uuid

EmitFn = Callable[[dict[str, Any]], Awaitable[None]]
_TABULAR_SPLIT_RE = re.compile(r"\s{2,}")


class LogCoalescer:
    def __init__(
        self,
        *,
        emit: EmitFn,
        idle_timeout_sec: float = 0.25,
        max_lines: int = 80,
    ) -> None:
        self._emit = emit
        self._idle_timeout_sec = max(0.05, float(idle_timeout_sec))
        self._max_lines = max(2, int(max_lines))
        self._lock = asyncio.Lock()
        self._pending: list[dict[str, Any]] = []
        self._group_id: str | None = None
        self._carry_row: dict[str, Any] | None = None
        self._flush_task: asyncio.Task[None] | None = None

    async def add(self, payload: Mapping[str, Any] | None) -> None:
        if not payload:
            return
        to_emit: list[dict[str, Any]] = []
        async with self._lock:
            row = dict(payload)
            if not self._pending and self._carry_row is not None:
                carry = dict(self._carry_row)
                self._carry_row = None
                carry_meta_raw = carry.get("meta")
                carry_meta = dict(carry_meta_raw) if isinstance(carry_meta_raw, Mapping) else {}
                carry_group_id = str(carry_meta.get("group_id") or "").strip()
                if carry_group_id:
                    row_meta_raw = row.get("meta")
                    row_meta = dict(row_meta_raw) if isinstance(row_meta_raw, Mapping) else {}
                    row_meta.setdefault("group_id", carry_group_id)
                    row["meta"] = row_meta
                if self._can_merge(carry, row):
                    self._group_id = carry_group_id or self._group_id
                    self._pending.append(carry)
                else:
                    to_emit.append(self._finalize_single_row(carry))
            if self._pending and not self._can_merge(self._pending[-1], row):
                flushed = self._drain_locked()
                if flushed:
                    to_emit.append(flushed)
            if not self._pending:
                self._group_id = uuid.uuid4().hex
            self._pending.append(row)
            if len(self._pending) >= self._max_lines:
                flushed = self._drain_locked()
                if flushed:
                    to_emit.append(flushed)
            else:
                self._reschedule_flush_locked()

        for item in to_emit:
            await self._emit(item)

    async def flush(self) -> None:
        to_emit: list[dict[str, Any]] = []
        async with self._lock:
            drained = self._drain_locked()
            if drained:
                to_emit.append(drained)
        for row in to_emit:
            await self._emit(row)

    async def close(self) -> None:
        await self.flush()
        carry_to_emit: dict[str, Any] | None = None
        async with self._lock:
            if self._carry_row is not None:
                carry_to_emit = self._finalize_single_row(self._carry_row)
                self._carry_row = None
        if carry_to_emit is not None:
            await self._emit(carry_to_emit)
        task = self._flush_task
        self._flush_task = None
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def _can_merge(self, left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
        left_level = str(left.get("level") or "").upper()
        right_level = str(right.get("level") or "").upper()
        if left_level != right_level:
            return False
        left_meta = left.get("meta")
        right_meta = right.get("meta")
        left_source = str(left_meta.get("source") if isinstance(left_meta, Mapping) else "")
        right_source = str(right_meta.get("source") if isinstance(right_meta, Mapping) else "")
        if left_source != right_source:
            return False
        left_stream = str(left_meta.get("stream") if isinstance(left_meta, Mapping) else "")
        right_stream = str(right_meta.get("stream") if isinstance(right_meta, Mapping) else "")
        if left_stream != right_stream:
            return False
        left_group_id = str(left_meta.get("group_id") if isinstance(left_meta, Mapping) else "").strip()
        right_group_id = str(right_meta.get("group_id") if isinstance(right_meta, Mapping) else "").strip()
        if left_group_id or right_group_id:
            if left_group_id != right_group_id:
                return False
        return True

    def _drain_locked(self) -> dict[str, Any] | None:
        if not self._pending:
            return None
        self._cancel_flush_locked()

        rows = self._pending
        self._pending = []
        group_id = self._group_id or uuid.uuid4().hex
        self._group_id = None

        messages = [str(item.get("message") or "") for item in rows]
        raw_messages = [str(item.get("raw_message") or item.get("message") or "") for item in rows]
        if len(messages) >= 2 and self._is_tabular_header(messages[-1]):
            carry = dict(rows[-1])
            carry_meta_raw = carry.get("meta")
            carry_meta = dict(carry_meta_raw) if isinstance(carry_meta_raw, Mapping) else {}
            if carry_meta.get("group_id") is None:
                carry_meta["group_id"] = group_id
            carry["meta"] = carry_meta
            self._carry_row = carry
            rows = rows[:-1]
            messages = messages[:-1]
            raw_messages = raw_messages[:-1]

        if not rows:
            return None

        first = dict(rows[0])
        merged_message = "\n".join(messages).strip("\n")
        merged_raw_message = "\n".join(raw_messages).strip("\n")

        meta_raw = first.get("meta")
        meta = dict(meta_raw) if isinstance(meta_raw, Mapping) else {}
        producer_group_id = str(meta.get("group_id") or "").strip()
        line_count = len(rows)
        if line_count > 1:
            meta["group_id"] = producer_group_id or group_id
            meta["line_count"] = line_count
            meta["collapsed"] = True
        else:
            meta.setdefault("line_count", 1)
            meta.setdefault("collapsed", False)

        first["message"] = merged_message
        first["raw_message"] = merged_raw_message
        first["meta"] = meta
        return first

    def _finalize_single_row(self, row: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(row)
        meta_raw = payload.get("meta")
        meta = dict(meta_raw) if isinstance(meta_raw, Mapping) else {}
        meta.setdefault("line_count", 1)
        meta.setdefault("collapsed", False)
        payload["meta"] = meta
        return payload

    def _reschedule_flush_locked(self) -> None:
        self._cancel_flush_locked()
        self._flush_task = asyncio.create_task(self._flush_after_idle())

    def _cancel_flush_locked(self) -> None:
        task = self._flush_task
        self._flush_task = None
        if task and not task.done():
            task.cancel()

    async def _flush_after_idle(self) -> None:
        try:
            await asyncio.sleep(self._idle_timeout_sec)
            await self.flush()
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    def _is_tabular_header(self, line: str) -> bool:
        text = str(line or "").strip()
        if not text:
            return False
        if any(char.isdigit() for char in text):
            return False
        if "/" in text:
            return False
        columns = [item.strip() for item in _TABULAR_SPLIT_RE.split(text) if item.strip()]
        if len(columns) < 3:
            return False
        for item in columns:
            if not any(char.isalpha() or char == "_" for char in item):
                return False
        return True
