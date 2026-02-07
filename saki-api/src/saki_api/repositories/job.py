"""
Job Repository - Data access layer for L3 Job operations.
"""

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.models.l3.job import Job
from saki_api.repositories.base import BaseRepository


class JobRepository(BaseRepository[Job]):
    def __init__(self, session: AsyncSession):
        super().__init__(Job, session)
