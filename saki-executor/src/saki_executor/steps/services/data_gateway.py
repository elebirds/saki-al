from __future__ import annotations

import asyncio
import uuid
from typing import Awaitable, Callable

from saki_executor.agent import codec as runtime_codec
from saki_executor.grpc_gen import runtime_control_pb2 as pb
from saki_executor.steps.contracts import ArtifactUploadTicket, FetchedPage
from saki_ir.codec import decode_payload
from saki_ir.errors import IRError
from saki_ir.geom import obb_to_vertices_local
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as irpb
from saki_ir.transport import ChunkAssembler, PayloadChunk

RequestFn = Callable[[pb.RuntimeMessage], Awaitable[pb.RuntimeMessage | list[pb.RuntimeMessage]]]
RequestGetterFn = Callable[[], RequestFn | None]

_DEFAULT_CHUNK_BYTES = 896 * 1024
_DEFAULT_MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024


class DataGateway:
    def __init__(self, request_message_getter: RequestGetterFn) -> None:
        self._request_message_getter = request_message_getter

    async def request_upload_ticket(
        self,
        *,
        task_id: str,
        artifact_name: str,
        content_type: str,
    ) -> ArtifactUploadTicket:
        request_message = self._required_request_message()
        ticket_response = await request_message(
            runtime_codec.build_upload_ticket_request_message(
                request_id=str(uuid.uuid4()),
                task_id=task_id,
                artifact_name=artifact_name,
                content_type=content_type,
            )
        )
        if isinstance(ticket_response, list):
            if not ticket_response:
                raise RuntimeError("upload ticket 请求返回空响应")
            ticket_response = ticket_response[0]
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
        task_id: str,
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
                task_id=task_id,
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
                raise asyncio.CancelledError("step stop requested")
        return items

    async def fetch_page(
        self,
        *,
        task_id: str,
        query_type: str,
        project_id: str,
        commit_id: str,
        cursor: str | None,
        limit: int,
    ) -> FetchedPage:
        request_message = self._required_request_message()
        response = await request_message(
            runtime_codec.build_data_request_message(
                request_id=str(uuid.uuid4()),
                task_id=task_id,
                query_type=query_type,
                project_id=project_id,
                commit_id=commit_id,
                cursor=cursor,
                limit=limit,
                preferred_chunk_bytes=_DEFAULT_CHUNK_BYTES,
                max_uncompressed_bytes=_DEFAULT_MAX_UNCOMPRESSED_BYTES,
            )
        )
        messages = response if isinstance(response, list) else [response]
        if not messages:
            raise RuntimeError("data request 返回空响应")

        reply_to = ""
        query_type_text = ""
        next_cursor: str | None = None
        assemblers: dict[str, ChunkAssembler] = {}

        for message in messages:
            payload_type = message.WhichOneof("payload")
            if payload_type == "error":
                error_payload = runtime_codec.parse_error(message.error)
                raise RuntimeError(str(error_payload.get("error") or "data request failed"))
            if payload_type != "data_response":
                raise RuntimeError(f"unexpected data response payload: {payload_type}")

            data_response = message.data_response
            reply_to = str(data_response.reply_to or reply_to)
            query_type_text = runtime_codec.query_type_to_text(data_response.query_type)

            if data_response.next_cursor:
                if not data_response.is_last_chunk:
                    raise RuntimeError("next_cursor 仅允许出现在最后一片")
                next_cursor = str(data_response.next_cursor)

            payload_id = str(data_response.payload_id or "")
            if not payload_id:
                raise RuntimeError("data_response.payload_id 不能为空")

            assembler = assemblers.get(payload_id)
            if assembler is None:
                assembler = ChunkAssembler(payload_id=payload_id, reply_to=reply_to)
                assemblers[payload_id] = assembler
            assembler.add(_to_payload_chunk(data_response))

        if len(assemblers) != 1:
            raise RuntimeError(f"单页仅允许一个 payload_id，实际={len(assemblers)}")

        assembler = next(iter(assemblers.values()))
        if not assembler.is_complete():
            raise RuntimeError("payload 分片未收齐")

        encoded = assembler.build()
        try:
            batch = decode_payload(
                encoded,
                normalize_output=True,
                max_uncompressed_size=_DEFAULT_MAX_UNCOMPRESSED_BYTES,
            )
        except IRError as exc:
            raise RuntimeError(f"decode payload 失败: {exc.message}") from exc

        items = _batch_to_items(batch, query_type_text)
        return FetchedPage(
            request_id=str(messages[0].data_response.request_id or ""),
            reply_to=reply_to,
            task_id=str(messages[0].data_response.task_id or ""),
            query_type=query_type_text,
            items=items,
            next_cursor=next_cursor,
        )

    def _required_request_message(self) -> RequestFn:
        request_message = self._request_message_getter()
        if request_message is None:
            raise RuntimeError("task manager request transport is not configured")
        return request_message


def _to_payload_chunk(data_response: pb.DataResponse) -> PayloadChunk:
    return PayloadChunk(
        payload_id=str(data_response.payload_id or ""),
        chunk_index=int(data_response.chunk_index),
        chunk_count=int(data_response.chunk_count),
        header_proto=bytes(data_response.header_proto),
        payload_chunk=bytes(data_response.payload_chunk),
        payload_total_size=int(data_response.payload_total_size),
        payload_checksum_crc32c=int(data_response.payload_checksum_crc32c),
        chunk_checksum_crc32c=int(data_response.chunk_checksum_crc32c),
        is_last_chunk=bool(data_response.is_last_chunk),
    )


def _batch_to_items(batch: irpb.DataBatchIR, query_type: str) -> list[dict]:
    query = (query_type or "").strip().lower()
    items: list[dict] = []
    for item in batch.items:
        kind = item.WhichOneof("item")
        if kind == "label" and query == "labels":
            label = item.label
            items.append({"id": label.id, "name": label.name, "color": label.color})
            continue
        if kind == "sample" and query in {"samples", "unlabeled_samples"}:
            sample = item.sample
            items.append(
                {
                    "id": sample.id,
                    "asset_hash": sample.asset_hash,
                    "download_url": sample.download_url,
                    "width": int(sample.width),
                    "height": int(sample.height),
                    "meta": runtime_codec.struct_to_dict(sample.meta),
                }
            )
            continue
        if kind == "annotation" and query == "annotations":
            ann = item.annotation
            bbox_xywh: list[float] = []
            obb_payload: dict | None = None
            if ann.geometry.HasField("rect"):
                rect = ann.geometry.rect
                bbox_xywh = [float(rect.x), float(rect.y), float(rect.width), float(rect.height)]
            elif ann.geometry.HasField("obb"):
                obb = ann.geometry.obb
                obb_payload = {
                    "cx": float(obb.cx),
                    "cy": float(obb.cy),
                    "width": float(obb.width),
                    "height": float(obb.height),
                    "angle_deg_ccw": float(obb.angle_deg_ccw),
                }
                vertices = obb_to_vertices_local(obb)
                xs = [point[0] for point in vertices]
                ys = [point[1] for point in vertices]
                bbox_xywh = [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]
            items.append(
                {
                    "id": ann.id,
                    "sample_id": ann.sample_id,
                    "category_id": ann.label_id,
                    "bbox_xywh": bbox_xywh,
                    "obb": obb_payload,
                    "source": _annotation_source_to_text(ann.source),
                    "confidence": float(ann.confidence),
                }
            )
    return items


def _annotation_source_to_text(source: int) -> str:
    mapping = {
        irpb.ANNOTATION_SOURCE_MANUAL: "manual",
        irpb.ANNOTATION_SOURCE_MODEL: "model",
        irpb.ANNOTATION_SOURCE_CONFIRMED_MODEL: "confirmed_model",
        irpb.ANNOTATION_SOURCE_SYSTEM: "system",
        irpb.ANNOTATION_SOURCE_IMPORTED: "imported",
    }
    return mapping.get(int(source), "")
