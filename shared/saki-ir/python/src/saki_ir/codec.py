from __future__ import annotations

"""saki-ir 编解码公共 API。

Spec: docs/IR_SPEC.md#9-encoded-payload
"""

from collections.abc import Iterator
import io
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


def _normalize_encode_params(compression_threshold: int, zstd_level: int) -> tuple[int, int]:
    # Spec: docs/IR_SPEC.md#9-encoded-payload
    if compression_threshold < 0:
        compression_threshold = 0
    if zstd_level == 0:
        zstd_level = 3
    if zstd_level < 1 or zstd_level > 22:
        raise IRError(ERR_IR_SCHEMA, "zstd_level 必须在 [1, 22]")
    return int(compression_threshold), int(zstd_level)


def _get_zstd_compressor(level: int):
    # Spec: docs/IR_SPEC.md#9-encoded-payload
    if _zstd is None:
        raise IRError(ERR_IR_COMPRESSION_UNSUPPORTED, "未安装 zstandard，无法使用 ZSTD 压缩")
    with _zstd_cache_lock:
        compressor = _zstd_compressors.get(level)
        if compressor is None:
            compressor = _zstd.ZstdCompressor(level=level)
            _zstd_compressors[level] = compressor
    return compressor


def _compress_zstd(data: bytes, level: int) -> bytes:
    compressor = _get_zstd_compressor(level)
    return compressor.compress(data)


def _decompress_zstd(data: bytes, *, max_uncompressed_size: int | None = None) -> bytes:
    # Spec: docs/IR_SPEC.md#9-encoded-payload
    if _zstd is None:
        raise IRError(ERR_IR_COMPRESSION_UNSUPPORTED, "未安装 zstandard，无法使用 ZSTD 解压")
    if max_uncompressed_size is not None and max_uncompressed_size < 0:
        raise IRError(ERR_IR_SCHEMA, "max_uncompressed_size 必须 >= 0")

    # 使用流式解压并在输出阶段强制上限，不信任 header.uncompressed_size。
    decompressor = _zstd.ZstdDecompressor()
    with decompressor.stream_reader(io.BytesIO(data)) as reader:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = reader.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if max_uncompressed_size is not None and total > max_uncompressed_size:
                raise IRError(
                    ERR_IR_COMPRESSION_UNSUPPORTED,
                    f"解压后数据超过上限: {total} > {max_uncompressed_size}",
                )
            chunks.append(chunk)
    return b"".join(chunks)


def decompress_raw(
    encoded: annotationirv1.EncodedPayload,
    *,
    max_uncompressed_size: int | None = None,
) -> bytes:
    """按 header.compression 获取 `payload_raw`。

    该函数只做「压缩层」处理：
    - `NONE`：直接返回 `payload` bytes
    - `ZSTD`：返回解压后的 bytes

    不会做 checksum 校验，也不会反序列化 `DataBatchIR`。

    Spec: docs/IR_SPEC.md#9-encoded-payload
    Spec: docs/IR_SPEC.md#10-header-only-behavior
    """

    header = read_header(encoded)
    payload = bytes(encoded.payload)
    if header.compression == annotationirv1.PAYLOAD_COMPRESSION_NONE:
        if max_uncompressed_size is not None and len(payload) > max_uncompressed_size:
            raise IRError(
                ERR_IR_COMPRESSION_UNSUPPORTED,
                f"未压缩 payload 超过上限: {len(payload)} > {max_uncompressed_size}",
            )
        return payload
    if header.compression == annotationirv1.PAYLOAD_COMPRESSION_ZSTD:
        return _decompress_zstd(payload, max_uncompressed_size=max_uncompressed_size)
    raise IRError(ERR_IR_COMPRESSION_UNSUPPORTED, f"不支持的 compression: {header.compression}")


def _verify_checksum(header: annotationirv1.PayloadHeader, payload_encoded: bytes) -> None:
    # Spec: docs/IR_SPEC.md#9-encoded-payload
    # checksum 覆盖范围固定为“压缩后 payload bytes（encoded payload bytes）”。
    if header.checksum_algo != annotationirv1.PAYLOAD_CHECKSUM_ALGO_CRC32C:
        raise IRError(ERR_IR_SCHEMA, f"不支持的 checksum_algo: {header.checksum_algo}")

    actual = checksum_crc32c(payload_encoded)
    if actual != header.checksum:
        raise IRError(
            ERR_IR_CHECKSUM_MISMATCH,
            f"checksum 不匹配: expected={header.checksum}, actual={actual}",
        )


def verify_checksum(encoded: annotationirv1.EncodedPayload) -> None:
    """仅执行 checksum 校验，不反序列化 DataBatchIR。

    行为：
    - 直接对 `encoded.payload` 计算并校验 `CRC32C(payload)`

    本函数不会解压，也不会调用 protobuf Parse/Unmarshal。

    Spec: docs/IR_SPEC.md#9-encoded-payload
    Spec: docs/IR_SPEC.md#10-header-only-behavior
    """

    header = read_header(encoded)
    payload_encoded = bytes(encoded.payload)
    _verify_checksum(header, payload_encoded)


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
    """将 `DataBatchIR` 编码为 `EncodedPayload`。

    该函数不会原地修改输入 `batch`，但会先调用 `validate_ir(batch)` 校验。
    编码流程：
    1. `payload_raw = batch.SerializeToString()`
    2. `checksum = CRC32C(payload_raw)`（覆盖未压缩 bytes）
    3. 按阈值选择 `NONE/ZSTD`
    4. 填充 header 与 stats

    Spec: docs/IR_SPEC.md#9-encoded-payload
    """

    # Spec: docs/IR_SPEC.md#9-encoded-payload
    compression_threshold, zstd_level = _normalize_encode_params(compression_threshold, zstd_level)
    validate_ir(batch)

    payload_raw = batch.SerializeToString()
    compression = annotationirv1.PAYLOAD_COMPRESSION_NONE
    payload = payload_raw
    if len(payload_raw) >= compression_threshold:
        payload = _compress_zstd(payload_raw, level=zstd_level)
        compression = annotationirv1.PAYLOAD_COMPRESSION_ZSTD
    checksum = checksum_crc32c(payload)

    stats = _collect_stats(batch)
    stats.payload_size = int(len(payload))
    stats.uncompressed_size = int(len(payload_raw))

    header = annotationirv1.PayloadHeader(
        schema=annotationirv1.PAYLOAD_SCHEMA_DATA_BATCH_IR,
        schema_version=2,
        codec=annotationirv1.PAYLOAD_CODEC_PROTOBUF,
        compression=compression,
        checksum_algo=annotationirv1.PAYLOAD_CHECKSUM_ALGO_CRC32C,
        checksum=checksum,
        stats=stats,
    )
    return annotationirv1.EncodedPayload(header=header, payload=payload)


def decode_payload(
    encoded: annotationirv1.EncodedPayload,
    *,
    normalize_output: bool = True,
    max_uncompressed_size: int = 64 * 1024 * 1024,
) -> annotationirv1.DataBatchIR:
    """从 `EncodedPayload` 解码出 `DataBatchIR`。

    参数：
    - `normalize_output=True`：解码后执行 `normalize_ir`（默认）
    - `normalize_output=False`：返回 payload 中的原始几何表示，不做规范化

    该函数会执行 checksum 校验；checksum 覆盖范围是未压缩 `payload_raw`。

    Spec: docs/IR_SPEC.md#9-encoded-payload
    """

    header = read_header(encoded)

    if header.schema != annotationirv1.PAYLOAD_SCHEMA_DATA_BATCH_IR:
        raise IRError(ERR_IR_SCHEMA, f"不支持的 schema: {header.schema}")
    if header.schema_version != 2:
        raise IRError(ERR_IR_SCHEMA, f"不支持的 schema_version: {header.schema_version}")

    # Spec: docs/IR_SPEC.md#9-encoded-payload
    payload_encoded = bytes(encoded.payload)
    _verify_checksum(header, payload_encoded)
    payload_raw = decompress_raw(encoded, max_uncompressed_size=max_uncompressed_size)

    batch = annotationirv1.DataBatchIR()
    if header.codec == annotationirv1.PAYLOAD_CODEC_PROTOBUF:
        batch.ParseFromString(payload_raw)
    elif header.codec == annotationirv1.PAYLOAD_CODEC_MSGPACK:
        raise IRError(ERR_IR_CODEC_UNSUPPORTED, "MSGPACK 编解码尚未实现")
    else:
        raise IRError(ERR_IR_CODEC_UNSUPPORTED, f"不支持的 codec: {header.codec}")

    if normalize_output:
        normalize_ir(batch)
    return batch


def read_header(encoded: annotationirv1.EncodedPayload | None) -> annotationirv1.PayloadHeader:
    """读取 header 副本，不触发解压/解码。

    返回值是 `PayloadHeader` 的 copy，调用方修改返回对象不会影响原始 payload。

    Spec: docs/IR_SPEC.md#10-header-only-behavior
    """

    if encoded is None or not encoded.HasField("header"):
        raise IRError(ERR_IR_SCHEMA, "encoded.header 缺失")
    header = annotationirv1.PayloadHeader()
    header.CopyFrom(encoded.header)
    return header


def iter_items(batch: annotationirv1.DataBatchIR) -> Iterator[annotationirv1.DataItemIR]:
    """按原始顺序迭代 `DataBatchIR.items`。"""

    for item in batch.items:
        yield item
