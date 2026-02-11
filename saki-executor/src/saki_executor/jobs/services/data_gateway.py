from __future__ import annotations

import asyncio
import uuid
from typing import Awaitable, Callable

from saki_executor.agent import codec as runtime_codec
from saki_executor.grpc_gen import runtime_control_pb2 as pb
from saki_executor.jobs.contracts import ArtifactUploadTicket, FetchedPage

RequestFn = Callable[[pb.RuntimeMessage], Awaitable[pb.RuntimeMessage]]
RequestGetterFn = Callable[[], RequestFn | None]


class DataGateway:
    def __init__(self, request_message_getter: RequestGetterFn) -> None:
        self._request_message_getter = request_message_getter

    async def request_upload_ticket(
        self,
        *,
        job_id: str,
        artifact_name: str,
        content_type: str,
    ) -> ArtifactUploadTicket:
        request_message = self._required_request_message()
        ticket_response = await request_message(
            runtime_codec.build_upload_ticket_request_message(
                request_id=str(uuid.uuid4()),
                job_id=job_id,
                artifact_name=artifact_name,
                content_type=content_type,
            )
        )
        payload_type = ticket_response.WhichOneof("payload")
        if payload_type == "error":
            error_payload = runtime_codec.parse_error(ticket_response.error)
            raise RuntimeError(str(error_payload.get("error") or "upload ticket request failed"))
        if payload_type != "upload_ticket_response":
            raise RuntimeError(f"unexpected upload ticket response payload: {payload_type}")
        return ArtifactUploadTicket.from_dict(
            runtime_codec.parse_upload_ticket_response(ticket_response.upload_ticket_response)
        )

    async def fetch_all(
        self,
        *,
        job_id: str,
        query_type: str,
        project_id: str,
        commit_id: str,
        limit: int = 1000,
        stop_event: asyncio.Event | None = None,
    ) -> list[dict]:
        items: list[dict] = []
        cursor: str | None = None
        while True:
            response = await self.fetch_page(
                job_id=job_id,
                query_type=query_type,
                project_id=project_id,
                commit_id=commit_id,
                cursor=cursor,
                limit=limit,
            )
            items.extend(response.items)
            cursor = response.next_cursor
            if not cursor:
                break
            if stop_event is not None and stop_event.is_set():
                raise asyncio.CancelledError("job stop requested")
        return items

    async def fetch_page(
        self,
        *,
        job_id: str,
        query_type: str,
        project_id: str,
        commit_id: str,
        cursor: str | None,
        limit: int,
    ) -> FetchedPage:
        request_message = self._required_request_message()
        response_message = await request_message(
            runtime_codec.build_data_request_message(
                request_id=str(uuid.uuid4()),
                job_id=job_id,
                query_type=query_type,
                project_id=project_id,
                commit_id=commit_id,
                cursor=cursor,
                limit=limit,
            )
        )
        payload_type = response_message.WhichOneof("payload")
        if payload_type == "error":
            error_payload = runtime_codec.parse_error(response_message.error)
            raise RuntimeError(str(error_payload.get("error") or "data request failed"))
        if payload_type != "data_response":
            raise RuntimeError(f"unexpected data response payload: {payload_type}")
        return FetchedPage.from_dict(runtime_codec.parse_data_response(response_message.data_response))

    def _required_request_message(self) -> RequestFn:
        request_message = self._request_message_getter()
        if request_message is None:
            raise RuntimeError("job manager request transport is not configured")
        return request_message

