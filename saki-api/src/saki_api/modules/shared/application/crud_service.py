"""Shared CRUD service base for module application services."""

from __future__ import annotations

import uuid
from typing import Generic, List, Type, TypeVar

from pydantic import BaseModel
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.exceptions import NotFoundAppException
from saki_api.infra.db.pagination import PaginationResponse
from saki_api.infra.db.query import FilterType, OrderByType, Pagination
from saki_api.infra.db.repository import BaseRepository
from saki_api.infra.db.transaction import transactional

ModelType = TypeVar("ModelType", bound=SQLModel)
RepoType = TypeVar("RepoType", bound=BaseRepository)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class CrudServiceBase(Generic[ModelType, RepoType, CreateSchemaType, UpdateSchemaType]):
    """Generic CRUD service base."""

    def __init__(
            self,
            model: Type[ModelType],
            repository_class: Type[RepoType],
            session: AsyncSession,
    ) -> None:
        self.model = model
        self.session = session
        self.repository: RepoType = repository_class(session)

    async def get_by_id(self, record_id: uuid.UUID) -> ModelType | None:
        return await self.repository.get_by_id(record_id)

    async def get_by_id_or_raise(self, record_id: uuid.UUID) -> ModelType:
        record = await self.repository.get_by_id(record_id)
        if not record:
            raise NotFoundAppException(f"Record{self.model.__name__} with ID {record_id} not found")
        return record

    async def get_one(self, filters: FilterType = None) -> ModelType | None:
        return await self.repository.get_one(filters)

    async def get_one_or_raise(self, filters: FilterType = None) -> ModelType:
        record = await self.repository.get_one(filters)
        if not record:
            raise NotFoundAppException(f"Record{self.model.__name__} with Filters {filters} not found")
        return record

    async def list(
            self,
            filters: FilterType = None,
            order_by: OrderByType = None,
    ) -> List[ModelType]:
        return await self.repository.list(filters=filters, order_by=order_by)

    async def list_paginated(
            self,
            pagination: Pagination = Pagination(),
            filters: FilterType = None,
            order_by: OrderByType = None,
    ) -> PaginationResponse[ModelType]:
        return await self.repository.list_paginated(
            pagination=pagination,
            filters=filters,
            order_by=order_by,
        )

    @transactional
    async def create(self, schema: CreateSchemaType) -> ModelType:
        data = schema.model_dump(exclude_unset=True)
        return await self.repository.create(data)

    @transactional
    async def update(
            self,
            record_id: uuid.UUID,
            schema: UpdateSchemaType,
    ) -> ModelType:
        return await self.repository.update_or_raise(record_id, schema.model_dump(exclude_unset=True))

    @transactional
    async def delete(self, record_id: uuid.UUID) -> ModelType:
        record = await self.get_by_id(record_id)
        success = await self.repository.delete(record_id)
        if not success:
            raise NotFoundAppException(f"Record{self.model.__name__} with ID {record_id} not found")
        return record
