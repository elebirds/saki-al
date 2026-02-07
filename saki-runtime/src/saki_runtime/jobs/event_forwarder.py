from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Dict, Optional

from loguru import logger

from saki_runtime.core.event_store import EventStore
from saki_runtime.schemas.enums import EventType
from saki_runtime.schemas.events import StatusPayload, EventEnvelope
from saki_runtime.jobs.state import JobStateMachine


PublishFn = Callable[[EventEnvelope], Awaitable[None]]
TerminalFn = Callable[[str], Awaitable[None]]


class EventForwarder:
    def __init__(self, publisher: Optional[PublishFn] = None, on_terminal: Optional[TerminalFn] = None):
        self._publisher: Optional[PublishFn] = publisher
        self._on_terminal: Optional[TerminalFn] = on_terminal
        self._tasks: Dict[str, asyncio.Task] = {}

    def set_publisher(self, publisher: Optional[PublishFn]) -> None:
        self._publisher = publisher

    def set_on_terminal(self, handler: Optional[TerminalFn]) -> None:
        self._on_terminal = handler

    def start(self, job_id: str, store: EventStore) -> None:
        if job_id in self._tasks:
            return
        self._tasks[job_id] = asyncio.create_task(self._run(job_id, store))

    async def _publish(self, event: EventEnvelope) -> None:
        if self._publisher:
            await self._publisher(event)

    async def _run(self, job_id: str, store: EventStore) -> None:
        last_seq = 0
        try:
            while True:
                for event in store.tail(last_seq + 1):
                    await self._publish(event)
                    last_seq = event.seq

                    if event.type == EventType.STATUS:
                        payload = StatusPayload.model_validate(event.payload)
                        if JobStateMachine.is_terminal(payload.status):
                            if self._on_terminal:
                                await self._on_terminal(job_id)
                            return

                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Event forwarder failed for job {job_id}: {e}")
        finally:
            self._tasks.pop(job_id, None)
