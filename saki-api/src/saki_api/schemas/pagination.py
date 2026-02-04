"""
Generic pagination response schema used across list endpoints.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Generic, List, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")
U = TypeVar("U")


class PaginationResponse(BaseModel, Generic[T]):
    """Standard paginated envelope.

    Exposes a fixed shape so frontend components can rely on consistent
    pagination metadata across endpoints.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    items: List[T]
    total: int = Field(ge=0, description="Total number of available records")
    offset: int = Field(ge=0, description="Current offset")
    limit: int = Field(ge=1, description="Page size")
    size: int = Field(ge=0, description="Number of records in this page")
    has_more: bool = Field(description="Whether more records exist after this page")

    @classmethod
    def from_items(
        cls,
        items: List[T],
        total: int,
        offset: int,
        limit: int,
    ) -> "PaginationResponse[T]":
        size = len(items)
        has_more = offset + size < total
        return cls(
            items=items,
            total=total,
            offset=offset,
            limit=limit,
            size=size,
            has_more=has_more,
        )

    def map(self, fn: Callable[[T], U]) -> "PaginationResponse[U]":
        """Map items synchronously while keeping pagination metadata."""
        mapped = [fn(item) for item in self.items]
        return PaginationResponse.from_items(mapped, self.total, self.offset, self.limit)

    async def map_async(self, fn: Callable[[T], Awaitable[U]]) -> "PaginationResponse[U]":
        """Async map helper for services needing awaitable transforms."""
        mapped = await asyncio.gather(*(fn(item) for item in self.items))
        return PaginationResponse.from_items(mapped, self.total, self.offset, self.limit)
