from __future__ import annotations

"""saki-ir 传输层分片工具。

用于 runtime gRPC 等分片场景，遵循：
- payload 按 encoded bytes 分片
- 校验以 payload encoded checksum 为准
"""

from dataclasses import dataclass, field
import math
import time
from typing import TypedDict
from uuid import uuid4

from saki_ir.codec import checksum_crc32c
from saki_ir.errors import ERR_IR_CHECKSUM_MISMATCH, ERR_IR_SCHEMA, IRError
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as annotationirv1

DEFAULT_CHUNK_BYTES = 896 * 1024


class PayloadChunk(TypedDict):
    payload_id: str
    chunk_index: int
    chunk_count: int
    header_proto: bytes
    payload_chunk: bytes
    payload_total_size: int
    payload_checksum_crc32c: int
    chunk_checksum_crc32c: int
    is_last_chunk: bool


def serialize_header(header: annotationirv1.PayloadHeader) -> bytes:
    """序列化 PayloadHeader。"""

    return header.SerializeToString()


def parse_header(data: bytes) -> annotationirv1.PayloadHeader:
    """反序列化 PayloadHeader。"""

    header = annotationirv1.PayloadHeader()
    header.ParseFromString(data)
    return header


def split_encoded_payload(
    encoded: annotationirv1.EncodedPayload,
    *,
    payload_id: str | None = None,
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
) -> list[PayloadChunk]:
    """将 EncodedPayload 拆成分片记录。"""

    if chunk_bytes <= 0:
        raise IRError(ERR_IR_SCHEMA, f"chunk_bytes 必须 > 0，当前={chunk_bytes}")

    if encoded is None or not encoded.HasField("header"):
        raise IRError(ERR_IR_SCHEMA, "encoded/header 缺失")

    pid = payload_id or str(uuid4())
    payload = bytes(encoded.payload)
    header_proto = serialize_header(encoded.header)
    payload_checksum = checksum_crc32c(payload)
    chunk_count = max(1, math.ceil(len(payload) / chunk_bytes))

    chunks: list[PayloadChunk] = []
    for idx in range(chunk_count):
        start = idx * chunk_bytes
        end = start + chunk_bytes
        chunk_payload = payload[start:end]
        chunks.append(
            PayloadChunk(
                payload_id=pid,
                chunk_index=idx,
                chunk_count=chunk_count,
                header_proto=header_proto,
                payload_chunk=chunk_payload,
                payload_total_size=len(payload),
                payload_checksum_crc32c=payload_checksum,
                chunk_checksum_crc32c=checksum_crc32c(chunk_payload),
                is_last_chunk=(idx == chunk_count - 1),
            )
        )
    return chunks


@dataclass
class ChunkAssembler:
    """按 payload_id 组装分片，支持幂等重复片。"""

    payload_id: str
    reply_to: str = ""
    first_seen_at: float = field(default_factory=time.time)
    _chunk_count: int | None = None
    _header_proto: bytes | None = None
    _payload_total_size: int | None = None
    _payload_checksum: int | None = None
    _chunks: dict[int, bytes] = field(default_factory=dict)

    def add(self, chunk: PayloadChunk) -> bool:
        """添加分片。返回是否已完整。"""

        if chunk["payload_id"] != self.payload_id:
            raise IRError(ERR_IR_SCHEMA, "payload_id 不匹配")

        self._assert_consistent(chunk)
        idx = int(chunk["chunk_index"])
        payload_chunk = bytes(chunk["payload_chunk"])
        chunk_checksum = int(chunk["chunk_checksum_crc32c"]) & 0xFFFFFFFF
        if checksum_crc32c(payload_chunk) != chunk_checksum:
            raise IRError(ERR_IR_CHECKSUM_MISMATCH, f"chunk checksum 不匹配: index={idx}")

        old = self._chunks.get(idx)
        if old is not None:
            if old != payload_chunk:
                raise IRError(ERR_IR_SCHEMA, f"chunk 冲突: index={idx}")
            return self.is_complete()

        self._chunks[idx] = payload_chunk
        return self.is_complete()

    def is_complete(self) -> bool:
        if self._chunk_count is None:
            return False
        return len(self._chunks) == self._chunk_count

    def build(self) -> annotationirv1.EncodedPayload:
        """构建完整 EncodedPayload。"""

        if not self.is_complete():
            raise IRError(ERR_IR_SCHEMA, "chunk 未收齐")
        if self._chunk_count is None or self._header_proto is None:
            raise IRError(ERR_IR_SCHEMA, "chunk 元信息缺失")

        payload = b"".join(self._chunks[idx] for idx in range(self._chunk_count))
        if self._payload_total_size is None or len(payload) != self._payload_total_size:
            raise IRError(
                ERR_IR_SCHEMA,
                f"payload_total_size 不一致: expected={self._payload_total_size} actual={len(payload)}",
            )
        actual_checksum = checksum_crc32c(payload)
        if self._payload_checksum is None or actual_checksum != self._payload_checksum:
            raise IRError(
                ERR_IR_CHECKSUM_MISMATCH,
                f"payload checksum 不匹配: expected={self._payload_checksum} actual={actual_checksum}",
            )

        encoded = annotationirv1.EncodedPayload()
        encoded.header.CopyFrom(parse_header(self._header_proto))
        encoded.payload = payload
        return encoded

    def header_copy(self) -> annotationirv1.PayloadHeader:
        """从分片复制 header（header-only 使用）。"""

        if self._header_proto is None:
            raise IRError(ERR_IR_SCHEMA, "header_proto 缺失")
        return parse_header(self._header_proto)

    def _assert_consistent(self, chunk: PayloadChunk) -> None:
        chunk_count = int(chunk["chunk_count"])
        if chunk_count <= 0:
            raise IRError(ERR_IR_SCHEMA, f"chunk_count 非法: {chunk_count}")
        idx = int(chunk["chunk_index"])
        if idx < 0 or idx >= chunk_count:
            raise IRError(ERR_IR_SCHEMA, f"chunk_index 越界: {idx}/{chunk_count}")

        header_proto = bytes(chunk["header_proto"])
        if not header_proto:
            raise IRError(ERR_IR_SCHEMA, "header_proto 不能为空")
        payload_total_size = int(chunk["payload_total_size"])
        payload_checksum = int(chunk["payload_checksum_crc32c"]) & 0xFFFFFFFF

        if self._chunk_count is None:
            self._chunk_count = chunk_count
            self._header_proto = header_proto
            self._payload_total_size = payload_total_size
            self._payload_checksum = payload_checksum
            return

        if self._chunk_count != chunk_count:
            raise IRError(ERR_IR_SCHEMA, "chunk_count 不一致")
        if self._header_proto != header_proto:
            raise IRError(ERR_IR_SCHEMA, "header_proto 不一致")
        if self._payload_total_size != payload_total_size:
            raise IRError(ERR_IR_SCHEMA, "payload_total_size 不一致")
        if self._payload_checksum != payload_checksum:
            raise IRError(ERR_IR_SCHEMA, "payload_checksum 不一致")


class CompletedPayloadCache:
    """payload 完成态去重缓存。"""

    def __init__(self, ttl_seconds: int = 300):
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._cache: dict[tuple[str, str], float] = {}

    def mark_done(self, reply_to: str, payload_id: str) -> None:
        self._cache[(reply_to, payload_id)] = time.time()
        self._cleanup()

    def is_done(self, reply_to: str, payload_id: str) -> bool:
        self._cleanup()
        return (reply_to, payload_id) in self._cache

    def _cleanup(self) -> None:
        now = time.time()
        expired = [key for key, ts in self._cache.items() if now-ts > self._ttl_seconds]
        for key in expired:
            self._cache.pop(key, None)
