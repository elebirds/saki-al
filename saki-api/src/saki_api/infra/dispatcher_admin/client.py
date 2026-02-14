"""Async client for dispatcher_admin gRPC service."""

from __future__ import annotations

import asyncio
import uuid
from typing import Sequence

import grpc
from loguru import logger

from saki_api.grpc_gen import dispatcher_admin_pb2 as pb
from saki_api.grpc_gen import dispatcher_admin_pb2_grpc as pb_grpc


class DispatcherAdminClient:
    def __init__(self, *, target: str, internal_token: str, timeout_sec: int = 5):
        self.target = str(target or "").strip()
        self.internal_token = str(internal_token or "").strip()
        self.timeout_sec = max(1, int(timeout_sec or 5))
        self._channel: grpc.aio.Channel | None = None
        self._stub: pb_grpc.DispatcherAdminStub | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.target)

    async def close(self) -> None:
        if self._channel is None:
            return
        await self._channel.close()
        logger.info("dispatcher_admin connection closed target={}", self.target)
        self._channel = None
        self._stub = None

    def _metadata(self) -> Sequence[tuple[str, str]]:
        if not self.internal_token:
            return ()
        return (("x-internal-token", self.internal_token),)

    async def _get_stub(self) -> pb_grpc.DispatcherAdminStub:
        if not self.enabled:
            raise RuntimeError("dispatcher admin target is empty")
        if self._stub is None:
            self._channel = grpc.aio.insecure_channel(self.target)
            try:
                await asyncio.wait_for(self._channel.channel_ready(), timeout=self.timeout_sec)
            except Exception:
                await self._channel.close()
                self._channel = None
                raise
            self._stub = pb_grpc.DispatcherAdminStub(self._channel)
            logger.info("dispatcher_admin connection established target={}", self.target)
        return self._stub

    async def start_loop(self, loop_id: str, *, command_id: str | None = None) -> pb.CommandResponse:
        stub = await self._get_stub()
        return await stub.StartLoop(
            pb.LoopCommandRequest(command_id=command_id or str(uuid.uuid4()), loop_id=str(loop_id)),
            timeout=self.timeout_sec,
            metadata=self._metadata(),
        )

    async def pause_loop(self, loop_id: str, *, command_id: str | None = None) -> pb.CommandResponse:
        stub = await self._get_stub()
        return await stub.PauseLoop(
            pb.LoopCommandRequest(command_id=command_id or str(uuid.uuid4()), loop_id=str(loop_id)),
            timeout=self.timeout_sec,
            metadata=self._metadata(),
        )

    async def resume_loop(self, loop_id: str, *, command_id: str | None = None) -> pb.CommandResponse:
        stub = await self._get_stub()
        return await stub.ResumeLoop(
            pb.LoopCommandRequest(command_id=command_id or str(uuid.uuid4()), loop_id=str(loop_id)),
            timeout=self.timeout_sec,
            metadata=self._metadata(),
        )

    async def stop_loop(self, loop_id: str, *, command_id: str | None = None) -> pb.CommandResponse:
        stub = await self._get_stub()
        return await stub.StopLoop(
            pb.LoopCommandRequest(command_id=command_id or str(uuid.uuid4()), loop_id=str(loop_id)),
            timeout=self.timeout_sec,
            metadata=self._metadata(),
        )

    async def confirm_loop(
            self,
            loop_id: str,
            *,
            force: bool = False,
            command_id: str | None = None,
    ) -> pb.CommandResponse:
        stub = await self._get_stub()
        return await stub.ConfirmLoop(
            pb.ConfirmLoopRequest(
                command_id=command_id or str(uuid.uuid4()),
                loop_id=str(loop_id),
                force=bool(force),
            ),
            timeout=self.timeout_sec,
            metadata=self._metadata(),
        )

    async def stop_round(
            self,
            round_id: str,
            *,
            reason: str = "",
            command_id: str | None = None,
    ) -> pb.CommandResponse:
        stub = await self._get_stub()
        return await stub.StopRound(
            pb.RoundCommandRequest(
                command_id=command_id or str(uuid.uuid4()),
                round_id=str(round_id),
                reason=str(reason or ""),
            ),
            timeout=self.timeout_sec,
            metadata=self._metadata(),
        )

    async def stop_job(self, job_id: str, *, reason: str = "", command_id: str | None = None) -> pb.CommandResponse:
        # backward alias for existing callers
        return await self.stop_round(job_id, reason=reason, command_id=command_id)

    async def stop_step(
            self,
            step_id: str,
            *,
            reason: str = "",
            command_id: str | None = None,
    ) -> pb.CommandResponse:
        stub = await self._get_stub()
        return await stub.StopStep(
            pb.StepCommandRequest(
                command_id=command_id or str(uuid.uuid4()),
                step_id=str(step_id),
                reason=str(reason or ""),
            ),
            timeout=self.timeout_sec,
            metadata=self._metadata(),
        )

    async def stop_task(self, task_id: str, *, reason: str = "", command_id: str | None = None) -> pb.CommandResponse:
        # backward alias for existing callers
        return await self.stop_step(task_id, reason=reason, command_id=command_id)

    async def trigger_dispatch(self, *, step_id: str = "", command_id: str | None = None) -> pb.CommandResponse:
        stub = await self._get_stub()
        return await stub.TriggerDispatch(
            pb.TriggerDispatchRequest(
                command_id=command_id or str(uuid.uuid4()),
                step_id=str(step_id or ""),
            ),
            timeout=self.timeout_sec,
            metadata=self._metadata(),
        )

    async def get_runtime_summary(self) -> pb.RuntimeSummaryResponse:
        stub = await self._get_stub()
        return await stub.GetRuntimeSummary(
            pb.RuntimeSummaryRequest(),
            timeout=self.timeout_sec,
            metadata=self._metadata(),
        )

    async def get_executor(self, executor_id: str) -> pb.ExecutorReadResponse:
        stub = await self._get_stub()
        return await stub.GetExecutor(
            pb.ExecutorReadRequest(executor_id=str(executor_id)),
            timeout=self.timeout_sec,
            metadata=self._metadata(),
        )

    async def list_executors(self) -> pb.ExecutorListResponse:
        stub = await self._get_stub()
        return await stub.ListExecutors(
            pb.ExecutorListRequest(),
            timeout=self.timeout_sec,
            metadata=self._metadata(),
        )
