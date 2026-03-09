from __future__ import annotations

from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.db.repository import BaseRepository
from saki_api.modules.runtime.domain.runtime_release import RuntimeRelease


class RuntimeReleaseRepository(BaseRepository[RuntimeRelease]):
    def __init__(self, session: AsyncSession):
        super().__init__(RuntimeRelease, session)

    async def get_by_component_version(
        self,
        *,
        component_type: str,
        component_name: str,
        version: str,
    ) -> Optional[RuntimeRelease]:
        stmt = select(RuntimeRelease).where(
            RuntimeRelease.component_type == component_type,
            RuntimeRelease.component_name == component_name,
            RuntimeRelease.version == version,
        )
        rows = await self.session.exec(stmt)
        return rows.first()
