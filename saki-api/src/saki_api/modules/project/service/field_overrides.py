"""
Helpers for explicit-field override resolution.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


async def get_or_override(
    *,
    schema: BaseModel,
    field_name: str,
    fallback: Callable[[], Awaitable[T]],
    transform: Callable[[Any], T] | None = None,
) -> T:
    """
    Return explicitly provided field value, otherwise fallback value.
    """
    if field_name in schema.model_fields_set:
        explicit_value = getattr(schema, field_name)
        return transform(explicit_value) if transform else explicit_value

    fallback_value = await fallback()
    return transform(fallback_value) if transform else fallback_value


async def get_or_overload(
    *,
    schema: BaseModel,
    field_name: str,
    fallback: Callable[[], Awaitable[T]],
    transform: Callable[[Any], T] | None = None,
) -> T:
    """
    Alias of get_or_override for naming compatibility.
    """
    return await get_or_override(
        schema=schema,
        field_name=field_name,
        fallback=fallback,
        transform=transform,
    )
