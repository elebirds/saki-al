"""
Annotation Working Area Service - Redis-backed snapshot cache.
"""

import json
import uuid
from typing import Any, Dict, Optional

from saki_api.core.config import settings
from saki_api.infra.cache.redis import build_working_key, get_redis_client


class AnnotationWorkingService:
    """
    Service for managing Working Area annotations in Redis.
    """

    KEY_SEQ = "__seq__"
    KEY_META = "__meta__"
    KEY_BASE_COMMIT = "__base_commit_id__"
    KEY_DIRTY = "__dirty__"

    def _build_key(
            self,
            project_id: uuid.UUID,
            sample_id: uuid.UUID,
            user_id: uuid.UUID,
            branch_name: str,
    ) -> str:
        return build_working_key(
            project_id=str(project_id),
            user_id=str(user_id),
            sample_id=str(sample_id),
            branch_name=branch_name,
        )

    @staticmethod
    def _decode_key(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    def _parse_hash(self, raw: Dict[Any, Any]) -> Dict[str, Any]:
        annotations = []
        meta: Dict[str, Any] = {}
        seq = 0
        base_commit_id: Optional[str] = None
        dirty = 0

        for key, value in raw.items():
            field = self._decode_key(key)
            if field == self.KEY_SEQ:
                try:
                    seq = int(self._decode_key(value))
                except (ValueError, TypeError):
                    seq = 0
                continue
            if field == self.KEY_META:
                try:
                    meta = json.loads(value) if value else {}
                except json.JSONDecodeError:
                    meta = {}
                continue
            if field == self.KEY_BASE_COMMIT:
                base_value = self._decode_key(value)
                base_commit_id = base_value or None
                continue
            if field == self.KEY_DIRTY:
                try:
                    dirty = int(self._decode_key(value))
                except (ValueError, TypeError):
                    dirty = 0
                continue
            try:
                annotations.append(json.loads(value))
            except json.JSONDecodeError:
                continue

        return {
            "annotations": annotations,
            "meta": meta,
            "seq": seq,
            "base_commit_id": base_commit_id,
            "dirty": dirty,
        }

    async def set_snapshot(
            self,
            project_id: uuid.UUID,
            sample_id: uuid.UUID,
            user_id: uuid.UUID,
            branch_name: str,
            payload: Dict[str, Any],
            base_commit_id: Optional[uuid.UUID] = None,
            seq: int = 0,
            dirty: int = 0,
    ) -> None:
        redis = get_redis_client()
        key = self._build_key(project_id, sample_id, user_id, branch_name)
        annotations = payload.get("annotations") or []
        meta = payload.get("meta") or {}

        mapping = {}
        for item in annotations:
            group_id = item.get("group_id") or item.get("groupId")
            lineage_id = item.get("lineage_id") or item.get("lineageId")
            item_id = item.get("id") or item.get("annotation_id") or lineage_id or group_id
            if not item_id:
                continue
            if group_id:
                item["group_id"] = str(group_id)
            if lineage_id:
                item["lineage_id"] = str(lineage_id)
            item["id"] = str(item_id)
            mapping[str(item_id)] = json.dumps(item, ensure_ascii=False, default=str)

        async with redis.pipeline() as pipe:
            pipe.delete(key)
            if mapping:
                pipe.hset(key, mapping=mapping)
            pipe.hset(key, self.KEY_SEQ, str(seq))
            pipe.hset(key, self.KEY_META, json.dumps(meta, ensure_ascii=False, default=str))
            pipe.hset(
                key,
                self.KEY_BASE_COMMIT,
                str(base_commit_id) if base_commit_id else "",
            )
            pipe.hset(key, self.KEY_DIRTY, str(dirty))
            pipe.expire(key, settings.REDIS_WORKING_TTL_SECONDS)
            await pipe.execute()

    async def get_snapshot(
            self,
            project_id: uuid.UUID,
            sample_id: uuid.UUID,
            user_id: uuid.UUID,
            branch_name: str,
    ) -> Optional[Dict[str, Any]]:
        redis = get_redis_client()
        key = self._build_key(project_id, sample_id, user_id, branch_name)
        raw = await redis.hgetall(key)
        if not raw:
            return None
        return self._parse_hash(raw)

    async def get_snapshot_payload(
            self,
            project_id: uuid.UUID,
            sample_id: uuid.UUID,
            user_id: uuid.UUID,
            branch_name: str,
    ) -> Optional[Dict[str, Any]]:
        snapshot = await self.get_snapshot(project_id, sample_id, user_id, branch_name)
        if not snapshot:
            return None
        return {
            "annotations": snapshot.get("annotations") or [],
            "meta": snapshot.get("meta") or {},
        }

    async def set_working(
            self,
            project_id: uuid.UUID,
            sample_id: uuid.UUID,
            user_id: uuid.UUID,
            branch_name: str,
            payload: Dict[str, Any],
    ) -> None:
        await self.set_snapshot(
            project_id=project_id,
            sample_id=sample_id,
            user_id=user_id,
            branch_name=branch_name,
            payload=payload,
            base_commit_id=None,
            seq=0,
        )

    async def get_working(
            self,
            project_id: uuid.UUID,
            sample_id: uuid.UUID,
            user_id: uuid.UUID,
            branch_name: str,
    ) -> Optional[Dict[str, Any]]:
        return await self.get_snapshot_payload(project_id, sample_id, user_id, branch_name)

    async def delete_working(
            self,
            project_id: uuid.UUID,
            sample_id: uuid.UUID,
            user_id: uuid.UUID,
            branch_name: str,
    ) -> int:
        redis = get_redis_client()
        key = self._build_key(project_id, sample_id, user_id, branch_name)
        return await redis.delete(key)
