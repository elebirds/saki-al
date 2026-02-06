"""
Annotation Sync Service - Full snapshot + incremental sync pipeline.
"""

import json
import uuid
from typing import Any, Dict, List, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.config import settings
from saki_api.core.exceptions import BadRequestAppException
from saki_api.core.redis import get_redis_client
from saki_api.models.enums import AnnotationType, AnnotationSource
from saki_api.repositories.annotation import AnnotationRepository
from saki_api.repositories.annotation_draft import AnnotationDraftRepository
from saki_api.repositories.branch import BranchRepository
from saki_api.services.annotation_working import AnnotationWorkingService
from saki_api.utils.coordinate_converter import convert_annotation_data_to_backend


class AnnotationSyncService:
    """
    Service for full snapshot sync with Redis auto-promotion.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.working_service = AnnotationWorkingService()
        self.draft_repo = AnnotationDraftRepository(session)
        self.branch_repo = BranchRepository(session)
        self.annotation_repo = AnnotationRepository(session)

    @staticmethod
    def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        annotations = payload.get("annotations") or []
        meta = payload.get("meta") or {}
        return {"annotations": annotations, "meta": meta}

    @staticmethod
    def _coerce_annotation_type(value: Any) -> Optional[AnnotationType]:
        if value is None:
            return None
        if isinstance(value, AnnotationType):
            return value
        return AnnotationType(str(value))

    @staticmethod
    def _strip_parent_from_extra(extra: Dict[str, Any]) -> Dict[str, Any]:
        if not extra:
            return {}
        cleaned = dict(extra)
        cleaned.pop("parent_id", None)
        cleaned.pop("parentId", None)
        return cleaned

    def _ensure_item_ids(self, item: Dict[str, Any]) -> Dict[str, Any]:
        group_id = item.get("group_id") or item.get("groupId")
        lineage_id = item.get("lineage_id") or item.get("lineageId")
        item_id = item.get("id") or lineage_id or group_id

        if group_id:
            item["group_id"] = str(group_id)
        if lineage_id:
            item["lineage_id"] = str(lineage_id)
        if item_id:
            item["id"] = str(item_id)

        item["extra"] = self._strip_parent_from_extra(item.get("extra") or {})
        return item

    def _build_item_from_action(
            self,
            project_id: uuid.UUID,
            sample_id: uuid.UUID,
            user_id: uuid.UUID,
            group_id: str,
            data: Dict[str, Any],
    ) -> Dict[str, Any]:
        label_id = data.get("label_id") or data.get("labelId")
        if not label_id:
            raise BadRequestAppException("label_id is required for sync actions")
        lineage_id = data.get("lineage_id") or data.get("lineageId")
        if not lineage_id:
            raise BadRequestAppException("lineage_id is required for sync actions")
        extra = self._strip_parent_from_extra(data.get("extra") or {})
        item_id = data.get("id") or lineage_id
        annotation_type = str(data.get("type") or AnnotationType.RECT.value)
        converted_data = convert_annotation_data_to_backend(annotation_type, data.get("data") or {})
        return {
            "id": str(item_id),
            "project_id": str(data.get("project_id") or project_id),
            "sample_id": str(data.get("sample_id") or sample_id),
            "label_id": str(label_id),
            "group_id": str(group_id),
            "lineage_id": str(lineage_id),
            "parent_id": str(data.get("parent_id")) if data.get("parent_id") else None,
            "view_role": data.get("view_role") or data.get("viewRole") or "main",
            "type": annotation_type,
            "source": str(data.get("source") or AnnotationSource.MANUAL.value),
            "data": converted_data,
            "extra": extra,
            "confidence": float(data.get("confidence") or 1.0),
            "annotator_id": str(data.get("annotator_id") or data.get("annotatorId") or user_id),
        }

    def _build_item_from_generated(
            self,
            project_id: uuid.UUID,
            sample_id: uuid.UUID,
            user_id: uuid.UUID,
            generated: Dict[str, Any],
            parent_group_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        extra = self._strip_parent_from_extra(generated.get("extra") or {})
        lineage_id = generated.get("lineage_id") or generated.get("lineageId") or generated.get("id") or str(
            uuid.uuid4())
        item_id = generated.get("id") or str(uuid.uuid4())
        group_id = generated.get("group_id") or generated.get("groupId") or parent_group_id
        if not group_id:
            raise BadRequestAppException("group_id is required for generated annotations")
        return {
            "id": str(item_id),
            "project_id": str(project_id),
            "sample_id": str(sample_id),
            "label_id": str(generated.get("label_id") or generated.get("labelId")),
            "group_id": str(group_id),
            "lineage_id": str(lineage_id),
            "parent_id": str(generated.get("parent_id")) if generated.get("parent_id") else None,
            "view_role": generated.get("view_role") or generated.get("viewRole") or extra.get("view") or "main",
            "type": str(generated.get("type") or AnnotationType.RECT.value),
            "source": str(generated.get("source") or AnnotationSource.SYSTEM.value),
            "data": generated.get("data") or {},
            "extra": extra,
            "confidence": float(generated.get("confidence") or 1.0),
            "annotator_id": str(generated.get("annotator_id") or generated.get("annotatorId") or user_id),
        }

    async def get_or_promote_snapshot(
            self,
            project_id: uuid.UUID,
            sample_id: uuid.UUID,
            user_id: uuid.UUID,
            branch_name: str,
    ) -> Dict[str, Any]:
        snapshot = await self.working_service.get_snapshot(
            project_id=project_id,
            sample_id=sample_id,
            user_id=user_id,
            branch_name=branch_name,
        )
        if snapshot:
            return snapshot

        branch = await self.branch_repo.get_by_name(project_id, branch_name)
        if not branch:
            raise BadRequestAppException(f"Branch '{branch_name}' not found in project")

        base_commit_id = branch.head_commit_id

        draft = await self.draft_repo.get_by_unique(
            project_id=project_id,
            sample_id=sample_id,
            user_id=user_id,
            branch_name=branch_name,
        )
        if draft and draft.payload:
            payload = self._normalize_payload(draft.payload)
            normalized_annotations = []
            for item in payload.get("annotations") or []:
                normalized_annotations.append(self._ensure_item_ids(item))
            payload["annotations"] = normalized_annotations
            await self.working_service.set_snapshot(
                project_id=project_id,
                sample_id=sample_id,
                user_id=user_id,
                branch_name=branch_name,
                payload=payload,
                base_commit_id=base_commit_id,
                seq=0,
            )
            return {
                "annotations": payload["annotations"],
                "meta": payload["meta"],
                "seq": 0,
                "base_commit_id": str(base_commit_id) if base_commit_id else None,
            }

        annotations = []
        if base_commit_id:
            committed = await self.annotation_repo.get_by_commit_and_sample(
                commit_id=base_commit_id,
                sample_id=sample_id,
            )
            for ann in committed:
                annotations.append({
                    "id": str(ann.id),
                    "project_id": str(ann.project_id),
                    "sample_id": str(ann.sample_id),
                    "label_id": str(ann.label_id),
                    "group_id": str(ann.group_id),
                    "lineage_id": str(ann.lineage_id),
                    "parent_id": str(ann.parent_id) if ann.parent_id else None,
                    "view_role": ann.view_role,
                    "type": str(ann.type.value if hasattr(ann.type, "value") else ann.type),
                    "source": str(ann.source.value if hasattr(ann.source, "value") else ann.source),
                    "data": ann.data or {},
                    "extra": ann.extra or {},
                    "confidence": ann.confidence,
                    "annotator_id": str(ann.annotator_id) if ann.annotator_id else None,
                })

        normalized_annotations = [self._ensure_item_ids(item) for item in annotations]
        payload = {"annotations": normalized_annotations, "meta": {}}
        await self.working_service.set_snapshot(
            project_id=project_id,
            sample_id=sample_id,
            user_id=user_id,
            branch_name=branch_name,
            payload=payload,
            base_commit_id=base_commit_id,
            seq=0,
        )
        return {
            "annotations": payload["annotations"],
            "meta": payload["meta"],
            "seq": 0,
            "base_commit_id": str(base_commit_id) if base_commit_id else None,
        }

    async def apply_actions(
            self,
            *,
            project_id: uuid.UUID,
            sample_id: uuid.UUID,
            user_id: uuid.UUID,
            branch_name: str,
            current_snapshot: Dict[str, Any],
            actions: List[Dict[str, Any]],
            meta: Optional[Dict[str, Any]],
            sync_handler,
            context,
    ) -> Dict[str, Any]:
        annotations = current_snapshot.get("annotations") or []
        items_by_id: Dict[str, Dict[str, Any]] = {}
        for item in annotations:
            normalized = self._ensure_item_ids(item)
            item_id = normalized.get("id")
            group_id = normalized.get("group_id")
            if item_id and group_id:
                items_by_id[str(item_id)] = normalized

        delete_keys: List[str] = []
        upserts: Dict[str, str] = {}

        def remove_group(group_id: str) -> None:
            for item_id, item in list(items_by_id.items()):
                if str(item.get("group_id")) == group_id:
                    items_by_id.pop(item_id, None)
                    delete_keys.append(item_id)

        for action in actions:
            action_type = action.get("type")
            group_id = action.get("group_id") or action.get("groupId")
            if not group_id:
                raise BadRequestAppException("group_id is required for sync actions")
            group_id = str(group_id)

            if action_type not in ("add", "update", "delete"):
                raise BadRequestAppException("Invalid sync action type")

            if action_type == "delete":
                existing = None
                for item in items_by_id.values():
                    if str(item.get("group_id")) == group_id:
                        existing = item
                        break
                remove_group(group_id)
                extra = (existing or {}).get("extra") or {}
                result = sync_handler.on_annotation_delete(
                    annotation_id=group_id,
                    extra=extra,
                    context=context,
                )
                if result.generated:
                    for gen in result.generated:
                        if gen.get("_action") in ("delete_children", "delete_group"):
                            target_group_id = gen.get("group_id") or gen.get("parent_id") or group_id
                            remove_group(str(target_group_id))
                else:
                    remove_group(group_id)
                continue

            data = action.get("data") or {}
            if not data:
                raise BadRequestAppException("Action data is required for add/update")

            item = self._build_item_from_action(
                project_id=project_id,
                sample_id=sample_id,
                user_id=user_id,
                group_id=group_id,
                data=data,
            )

            if action_type == "update":
                remove_group(group_id)

            ann_type = self._coerce_annotation_type(item.get("type"))
            label_id = item.get("label_id")
            extra = item.get("extra") or {}
            geometry = item.get("data") or {}

            if action_type == "add":
                result = sync_handler.on_annotation_create(
                    annotation_id=group_id,
                    label_id=str(label_id),
                    ann_type=ann_type,
                    data=geometry,
                    extra=extra,
                    context=context,
                )
            else:
                result = sync_handler.on_annotation_update(
                    annotation_id=group_id,
                    label_id=str(label_id) if label_id else None,
                    ann_type=ann_type,
                    data=geometry,
                    extra=extra,
                    context=context,
                )

            item_id = str(item.get("id") or group_id)
            items_by_id[item_id] = item
            upserts[item_id] = json.dumps(item, ensure_ascii=False, default=str)

            generated_items = []
            if result.generated:
                for gen in result.generated:
                    if gen.get("_action") in ("delete_children", "delete_group"):
                        target_group_id = gen.get("group_id") or gen.get("parent_id") or group_id
                        remove_group(str(target_group_id))
                        continue
                    if gen.get("_action") == "regenerate_children":
                        remove_group(group_id)
                        continue
                    generated_items.append(gen)

            for gen in generated_items:
                gen_item = self._build_item_from_generated(
                    project_id=project_id,
                    sample_id=sample_id,
                    user_id=user_id,
                    generated=gen,
                    parent_group_id=group_id,
                )
                gen_item_id = gen_item.get("id")
                if not gen_item_id:
                    continue
                items_by_id[str(gen_item_id)] = gen_item
                upserts[str(gen_item_id)] = json.dumps(gen_item, ensure_ascii=False, default=str)

        redis = get_redis_client()
        key = self.working_service._build_key(project_id, sample_id, user_id, branch_name)
        mark_dirty = len(actions) > 0
        async with redis.pipeline() as pipe:
            if delete_keys:
                pipe.hdel(key, *delete_keys)
            if upserts:
                pipe.hset(key, mapping=upserts)
            if meta is not None:
                pipe.hset(key, self.working_service.KEY_META, json.dumps(meta, ensure_ascii=False, default=str))
            if mark_dirty:
                pipe.hset(key, self.working_service.KEY_DIRTY, "1")
            pipe.hincrby(key, self.working_service.KEY_SEQ, 1)
            pipe.hgetall(key)
            pipe.expire(key, settings.REDIS_WORKING_TTL_SECONDS)
            results = await pipe.execute()

        raw_snapshot = results[-2] if len(results) >= 2 else {}
        parsed = self.working_service._parse_hash(raw_snapshot or {})
        return parsed
