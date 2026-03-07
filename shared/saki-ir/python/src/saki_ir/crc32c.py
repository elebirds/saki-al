from __future__ import annotations

_CRC32C_POLY = 0x82F63B78
_CRC32C_TABLE: list[int] | None = None

try:
    import google_crc32c  # type: ignore
except ImportError:  # pragma: no cover
    google_crc32c = None


def _build_crc32c_table() -> list[int]:
    table: list[int] = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ _CRC32C_POLY
            else:
                crc >>= 1
        table.append(crc & 0xFFFFFFFF)
    return table


def checksum_crc32c(data: bytes) -> int:
    """计算 CRC32C(Castagnoli)。"""

    if google_crc32c is not None:
        return int(google_crc32c.value(data)) & 0xFFFFFFFF

    global _CRC32C_TABLE
    if _CRC32C_TABLE is None:
        _CRC32C_TABLE = _build_crc32c_table()

    crc = 0xFFFFFFFF
    for b in data:
        crc = _CRC32C_TABLE[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return (~crc) & 0xFFFFFFFF
