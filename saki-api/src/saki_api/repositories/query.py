"""
Query parameters for list operations.
"""

from __future__ import annotations

from typing import Optional, List, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import ColumnElement

    # Type aliases for SQLAlchemy expressions
    # These are used for type hints but not enforced at runtime due to Pydantic's arbitrary_types_allowed
    WhereClause = Union[ColumnElement[bool], bool]
    OrderByClause = ColumnElement  # Order by can be ColumnElement or UnaryExpression (from desc/asc)
else:
    # Runtime fallback - use Any for runtime since we can't import SQLAlchemy types
    from typing import Any

    WhereClause = Any
    OrderByClause = Any

FilterType = Optional[List[WhereClause]]
OrderByType = Optional[List[OrderByClause]]

from pydantic import BaseModel, Field


class Pagination(BaseModel):
    """Pagination parameters."""

    offset: int = Field(default=0, ge=0, description="Number of records to skip")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum number of records to return")

    @property
    def page(self) -> int:
        """1-based page number derived from offset/limit."""
        return (self.offset // self.limit) + 1

    @classmethod
    def from_page(cls, page: int, limit: int) -> "Pagination":
        page = max(page, 1)
        return cls(offset=(page - 1) * limit, limit=limit)
