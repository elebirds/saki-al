"""
Annotation Working Area Service - Redis-backed high-frequency cache.
"""

import json
import uuid
from typing import Any, Dict, Optional

from saki_api.core.config import settings
from saki_api.core.redis import build_working_key, get_redis_client


class AnnotationWorkingService:
    """
    Service for managing Working Area annotations in Redis.
    """

    async def set_working(
            self,
            project_id: uuid.UUID,
            sample_id: uuid.UUID,
            user_id: uuid.UUID,
            branch_name: str,
            payload: Dict[str, Any],
    ) -> None:
        redis = get_redis_client()
        key = build_working_key(
            project_id=str(project_id),
            user_id=str(user_id),
            sample_id=str(sample_id),
            branch_name=branch_name,
        )
        await redis.set(
            key,
            json.dumps(payload, ensure_ascii=False),
            ex=settings.REDIS_WORKING_TTL_SECONDS,
        )

    async def get_working(
            self,
            project_id: uuid.UUID,
            sample_id: uuid.UUID,
            user_id: uuid.UUID,
            branch_name: str,
    ) -> Optional[Dict[str, Any]]:
        redis = get_redis_client()
        key = build_working_key(
            project_id=str(project_id),
            user_id=str(user_id),
            sample_id=str(sample_id),
            branch_name=branch_name,
        )
        raw = await redis.get(key)
        if not raw:
            return None
        return json.loads(raw)

    async def delete_working(
            self,
            project_id: uuid.UUID,
            sample_id: uuid.UUID,
            user_id: uuid.UUID,
            branch_name: str,
    ) -> int:
        redis = get_redis_client()
        key = build_working_key(
            project_id=str(project_id),
            user_id=str(user_id),
            sample_id=str(sample_id),
            branch_name=branch_name,
        )
        return await redis.delete(key)
