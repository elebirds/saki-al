from __future__ import annotations

import asyncio
import random
from typing import Awaitable, Callable, Optional

import grpc
from loguru import logger

from saki_runtime.agent.interceptors import AuthInterceptor, LoggingInterceptor
from saki_runtime.grpc_gen import runtime_agent_pb2 as pb2
from saki_runtime.grpc_gen import runtime_agent_pb2_grpc as pb2_grpc


MessageHandler = Callable[[pb2.AgentMessage], Awaitable[None]]
ConnectHandler = Callable[[], Awaitable[None]]


class GrpcStreamManager:
    def __init__(
        self,
        target: str,
        token: str,
        on_message: MessageHandler,
        on_connect: Optional[ConnectHandler] = None,
        initial_backoff: float = 1.0,
        max_backoff: float = 30.0,
        jitter_ratio: float = 0.2,
    ) -> None:
        self._target = target
        self._token = token
        self._on_message = on_message
        self._on_connect = on_connect
        self._outbox: asyncio.Queue[pb2.AgentMessage] = asyncio.Queue()
        self._running = False
        self._stop_event = asyncio.Event()
        self._initial_backoff = initial_backoff
        self._max_backoff = max_backoff
        self._jitter_ratio = jitter_ratio

    async def send(self, message: pb2.AgentMessage) -> None:
        await self._outbox.put(message)

    async def stop(self) -> None:
        self._stop_event.set()
        await self._outbox.put(pb2.AgentMessage())

    async def _request_iter(self):
        while self._running and not self._stop_event.is_set():
            message = await self._outbox.get()
            if self._stop_event.is_set():
                break
            yield message

    async def _run_once(self) -> None:
        interceptors = [AuthInterceptor(self._token), LoggingInterceptor()]
        async with grpc.aio.insecure_channel(self._target, interceptors=interceptors) as channel:
            stub = pb2_grpc.RuntimeAgentStub(channel)
            self._running = True
            try:
                if self._on_connect:
                    await self._on_connect()

                call = stub.Stream(self._request_iter())
                async for response in call:
                    try:
                        await self._on_message(response)
                    except Exception:
                        logger.exception("Failed to process incoming message")
            finally:
                self._running = False

    async def run_forever(self) -> None:
        attempt = 0
        while not self._stop_event.is_set():
            try:
                logger.info("Connecting to API gRPC at {}", self._target)
                await self._run_once()
                attempt = 0
            except Exception as e:
                self._running = False
                delay = min(self._max_backoff, self._initial_backoff * (2**attempt))
                jitter = random.uniform(0, delay * self._jitter_ratio)
                delay = delay + jitter
                attempt = min(attempt + 1, 10)
                logger.error("gRPC stream error: {}, retrying in {:.2f}s", e, delay)
                await asyncio.sleep(delay)
