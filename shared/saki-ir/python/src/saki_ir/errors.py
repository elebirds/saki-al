from __future__ import annotations

from dataclasses import dataclass

ERR_IR_SCHEMA = "ERR_IR_SCHEMA"
ERR_IR_GEOMETRY = "ERR_IR_GEOMETRY"
ERR_IR_CODEC_UNSUPPORTED = "ERR_IR_CODEC_UNSUPPORTED"
ERR_IR_COMPRESSION_UNSUPPORTED = "ERR_IR_COMPRESSION_UNSUPPORTED"
ERR_IR_CHECKSUM_MISMATCH = "ERR_IR_CHECKSUM_MISMATCH"
ERR_IR_DATAFRAME_UNAVAILABLE = "ERR_IR_DATAFRAME_UNAVAILABLE"


@dataclass(slots=True)
class IRError(Exception):
    """统一 IR 异常。"""

    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
