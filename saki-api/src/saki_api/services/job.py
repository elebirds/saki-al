"""
Job Service - L3 Job business logic.
"""

import uuid
from typing import Any, Dict

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.l3.job import Job
from saki_api.repositories.job import JobRepository
from saki_api.schemas.job import JobCreateRequest
from saki_api.services.base import BaseService


class JobService(BaseService[Job, JobRepository, JobCreateRequest, dict]):
    def __init__(self, session: AsyncSession):
        super().__init__(Job, JobRepository, session)

    async def update_fields(self, job_id: uuid.UUID, fields: Dict[str, Any]) -> Job:
        return await self.repository.update_or_raise(job_id, fields)
