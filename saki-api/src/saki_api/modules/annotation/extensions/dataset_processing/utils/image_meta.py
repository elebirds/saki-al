from __future__ import annotations

from io import BytesIO
from typing import Any

from fastapi import UploadFile
from PIL import Image


def _normalize_dpi(value: Any) -> int | None:
    if isinstance(value, (tuple, list)) and value:
        value = value[0]
    try:
        dpi = float(value)
    except (TypeError, ValueError):
        return None
    if dpi <= 0:
        return None
    return int(round(dpi))


def extract_image_meta_from_bytes(content: bytes) -> dict[str, Any]:
    if not content:
        return {}
    try:
        with Image.open(BytesIO(content)) as image:
            width, height = image.size
            result: dict[str, Any] = {
                "width": int(width),
                "height": int(height),
            }
            if image.format:
                result["format"] = str(image.format)
            if image.mode:
                result["mode"] = str(image.mode)
            dpi = _normalize_dpi((image.info or {}).get("dpi"))
            if dpi is not None:
                result["dpi"] = dpi
            return result
    except Exception:  # noqa: BLE001
        return {}


async def extract_image_meta_from_upload(file: UploadFile) -> dict[str, Any]:
    await file.seek(0)
    content = await file.read()
    await file.seek(0)
    return extract_image_meta_from_bytes(content)
