from __future__ import annotations

from collections.abc import Iterator
from threading import Lock

from saki_ir.crc32c import checksum_crc32c
from saki_ir.errors import (
    ERR_IR_CHECKSUM_MISMATCH,
    ERR_IR_CODEC_UNSUPPORTED,
    ERR_IR_COMPRESSION_UNSUPPORTED,
    ERR_IR_SCHEMA,
    IRError,
)
from saki_ir.normalize import normalize_ir, validate_ir
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as annotationirv1

try:
    import zstandard as _zstd  # type: ignore
except ImportError:  # pragma: no cover
    _zstd = None


_zstd_cache_lock = Lock()
_zstd_compressors: dict[int, object] = {}
_zstd_decompressor: object | None = None


def _normalize_encode_params(compression_threshold: int, zstd_level: int) -> tuple[int, int]:
    if compression_threshold < 0:
        compression_threshold = 0
    if zstd_level == 0:
        zstd_level = 3
    if zstd_level < 1 or zstd_level > 22:
        raise IRError(ERR_IR_SCHEMA, "zstd_level 必须在 [1, 22]")
    return int(compression_threshold), int(zstd_level)


def _get_zstd_compressor(level: int):
    if _zstd is None:
        raise IRError(ERR_IR_COMPRESSION_UNSUPPORTED, "未安装 zstandard，无法使用 ZSTD 压缩")
    with _zstd_cache_lock:
        compressor = _zstd_compressors.get(level)
        if compressor is None:
            compressor = _zstd.ZstdCompressor(level=level)
            _zstd_compressors[level] = compressor
    return compressor


def _get_zstd_decompressor():
    if _zstd is None:
        raise IRError(ERR_IR_COMPRESSION_UNSUPPORTED, "未安装 zstandard，无法使用 ZSTD 解压")
    global _zstd_decompressor
    with _zstd_cache_lock:
        if _zstd_decompressor is None:
            _zstd_decompressor = _zstd.ZstdDecompressor()
    return _zstd_decompressor


def _compress_zstd(data: bytes, level: int) -> bytes:
    compressor = _get_zstd_compressor(level)
    return compressor.compress(data)


def _decompress_zstd(data: bytes) -> bytes:
    decompressor = _get_zstd_decompressor()
    return decompressor.decompress(data)


def _collect_stats(batch: annotationirv1.DataBatchIR) -> annotationirv1.PayloadStats:
    stats = annotationirv1.PayloadStats()
    stats.item_count = len(batch.items)
    for item in batch.items:
        kind = item.WhichOneof("item")
        if kind == "annotation":
            stats.annotation_count += 1
        elif kind == "sample":
            stats.sample_count += 1
        elif kind == "label":
            stats.label_count += 1
    return stats


def encode_payload(
    batch: annotationirv1.DataBatchIR,
    *,
    compression_threshold: int = 32768,
    zstd_level: int = 3,
) -> annotationirv1.EncodedPayload:
    compression_threshold, zstd_level = _normalize_encode_params(compression_threshold, zstd_level)
    validate_ir(batch)

    payload_raw = batch.SerializeToString()
    checksum = checksum_crc32c(payload_raw)

    compression = annotationirv1.PAYLOAD_COMPRESSION_NONE
    payload = payload_raw
    if len(payload_raw) >= compression_threshold:
        payload = _compress_zstd(payload_raw, level=zstd_level)
        compression = annotationirv1.PAYLOAD_COMPRESSION_ZSTD

    stats = _collect_stats(batch)
    stats.payload_size = int(len(payload))
    stats.uncompressed_size = int(len(payload_raw))

    header = annotationirv1.PayloadHeader(
        schema=annotationirv1.PAYLOAD_SCHEMA_DATA_BATCH_IR,
        schema_version=1,
        codec=annotationirv1.PAYLOAD_CODEC_PROTOBUF,
        compression=compression,
        checksum_algo=annotationirv1.PAYLOAD_CHECKSUM_ALGO_CRC32C,
        checksum=checksum,
        stats=stats,
    )
    return annotationirv1.EncodedPayload(header=header, payload=payload)


def decode_payload(encoded: annotationirv1.EncodedPayload) -> annotationirv1.DataBatchIR:
    header = read_header(encoded)

    if header.schema != annotationirv1.PAYLOAD_SCHEMA_DATA_BATCH_IR:
        raise IRError(ERR_IR_SCHEMA, f"不支持的 schema: {header.schema}")
    if header.schema_version != 1:
        raise IRError(ERR_IR_SCHEMA, f"不支持的 schema_version: {header.schema_version}")

    payload = bytes(encoded.payload)
    if header.compression == annotationirv1.PAYLOAD_COMPRESSION_NONE:
        payload_raw = payload
    elif header.compression == annotationirv1.PAYLOAD_COMPRESSION_ZSTD:
        payload_raw = _decompress_zstd(payload)
    else:
        raise IRError(ERR_IR_COMPRESSION_UNSUPPORTED, f"不支持的 compression: {header.compression}")

    if header.checksum_algo == annotationirv1.PAYLOAD_CHECKSUM_ALGO_CRC32C:
        actual = checksum_crc32c(payload_raw)
        if actual != header.checksum:
            raise IRError(
                ERR_IR_CHECKSUM_MISMATCH,
                f"checksum 不匹配: expected={header.checksum}, actual={actual}",
            )
    else:
        raise IRError(ERR_IR_SCHEMA, f"不支持的 checksum_algo: {header.checksum_algo}")

    batch = annotationirv1.DataBatchIR()
    if header.codec == annotationirv1.PAYLOAD_CODEC_PROTOBUF:
        batch.ParseFromString(payload_raw)
    elif header.codec == annotationirv1.PAYLOAD_CODEC_MSGPACK:
        raise IRError(ERR_IR_CODEC_UNSUPPORTED, "MSGPACK 编解码尚未实现")
    else:
        raise IRError(ERR_IR_CODEC_UNSUPPORTED, f"不支持的 codec: {header.codec}")

    normalize_ir(batch)
    return batch


def read_header(encoded: annotationirv1.EncodedPayload | None) -> annotationirv1.PayloadHeader:
    if encoded is None or not encoded.HasField("header"):
        raise IRError(ERR_IR_SCHEMA, "encoded.header 缺失")
    header = annotationirv1.PayloadHeader()
    header.CopyFrom(encoded.header)
    return header


def iter_items(batch: annotationirv1.DataBatchIR) -> Iterator[annotationirv1.DataItemIR]:
    for item in batch.items:
        yield item
