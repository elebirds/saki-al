"""Annotation Sync Service - Full snapshot + incremental sync pipeline."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.core.config import settings
from saki_api.core.exceptions import BadRequestAppException
from saki_api.infra.cache.redis import get_redis_client
from saki_api.modules.annotation.domain.ir_geometry_codec import (
    normalize_annotation_payload,
    normalize_annotation_source,
    normalize_annotation_type,
    normalize_attrs,
)
from saki_api.modules.annotation.repo.annotation import AnnotationRepository
from saki_api.modules.annotation.repo.draft import AnnotationDraftRepository
from saki_api.modules.annotation.service.working import AnnotationWorkingService
from saki_api.modules.project.contracts import ProjectReadGateway
from saki_api.modules.shared.modeling.enums import AnnotationSource, AnnotationType


class AnnotationSyncService:
    """Service for full snapshot sync with Redis auto-promotion."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.working_service = AnnotationWorkingService()
        self.draft_repo = AnnotationDraftRepository(session)
        self.project_gateway = ProjectReadGateway(session)
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
        return normalize_annotation_type(value)

    @staticmethod
    def _strip_parent_from_attrs(attrs: Dict[str, Any]) -> Dict[str, Any]:
        if not attrs:
            return {}
        cleaned = dict(attrs)
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

        source = item.get("source") or AnnotationSource.MANUAL.value
        confidence = float(item.get("confidence") or 1.0)
        ann_type, geometry, attrs = normalize_annotation_payload(
            annotation_type=item.get("type") or AnnotationType.RECT.value,
            geometry_payload=item.get("geometry") or {},
            attrs_payload=self._strip_parent_from_attrs(normalize_attrs(item.get("attrs"))),
            confidence=confidence,
            source=source,
        )
        item["type"] = ann_type.value
        item["source"] = normalize_annotation_source(source).value
        item["geometry"] = geometry
        item["attrs"] = attrs
        item["confidence"] = confidence
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

        item_id = data.get("id") or lineage_id
        source = data.get("source") or AnnotationSource.MANUAL.value
        confidence = float(data.get("confidence") or 1.0)
        ann_type, geometry, attrs = normalize_annotation_payload(
            annotation_type=data.get("type") or AnnotationType.RECT.value,
            geometry_payload=data.get("geometry") or {},
            attrs_payload=self._strip_parent_from_attrs(data.get("attrs") or {}),
            confidence=confidence,
            source=source,
        )

        return {
            "id": str(item_id),
            "project_id": str(data.get("project_id") or project_id),
            "sample_id": str(data.get("sample_id") or sample_id),
            "label_id": str(label_id),
            "group_id": str(group_id),
            "lineage_id": str(lineage_id),
            "parent_id": str(data.get("parent_id")) if data.get("parent_id") else None,
            "view_role": data.get("view_role") or data.get("viewRole") or "main",
            "type": ann_type.value,
            "source": normalize_annotation_source(source).value,
            "geometry": geometry,
            "attrs": attrs,
            "confidence": confidence,
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
        attrs_input = self._strip_parent_from_attrs(generated.get("attrs") or {})
        lineage_id = generated.get("lineage_id") or generated.get("lineageId") or generated.get("id") or str(
            uuid.uuid4())
        item_id = generated.get("id") or str(uuid.uuid4())
        group_id = generated.get("group_id") or generated.get("groupId") or parent_group_id
        label_id = generated.get("label_id") or generated.get("labelId")
        if not group_id:
            raise BadRequestAppException("group_id is required for generated annotations")
        if not label_id:
            raise BadRequestAppException("label_id is required for generated annotations")

        source = generated.get("source") or AnnotationSource.SYSTEM.value
        confidence = float(generated.get("confidence") or 1.0)
        ann_type, geometry, attrs = normalize_annotation_payload(
            annotation_type=generated.get("type") or AnnotationType.RECT.value,
            geometry_payload=generated.get("geometry") or {},
            attrs_payload=attrs_input,
            confidence=confidence,
            source=source,
        )

        return {
            "id": str(item_id),
            "project_id": str(project_id),
            "sample_id": str(sample_id),
            "label_id": str(label_id),
            "group_id": str(group_id),
            "lineage_id": str(lineage_id),
            "parent_id": str(generated.get("parent_id")) if generated.get("parent_id") else None,
            "view_role": generated.get("view_role") or generated.get("viewRole") or attrs.get("view") or "main",
            "type": ann_type.value,
            "source": normalize_annotation_source(source).value,
            "geometry": geometry,
            "attrs": attrs,
            "confidence": confidence,
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

        branch = await self.project_gateway.get_branch_by_name(project_id, branch_name)
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
                    "geometry": ann.geometry or {},
                    "attrs": ann.attrs or {},
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

    def _index_snapshot_annotations(self, annotations: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        items_by_id: Dict[str, Dict[str, Any]] = {}
        for item in annotations:
            normalized = self._ensure_item_ids(item)
            item_id = normalized.get("id")
            group_id = normalized.get("group_id")
            if item_id and group_id:
                items_by_id[str(item_id)] = normalized
        return items_by_id

    @staticmethod
    def _remove_group_items(
            *,
            items_by_id: Dict[str, Dict[str, Any]],
            group_id: str,
            delete_keys: List[str],
    ) -> None:
        for item_id, item in list(items_by_id.items()):
            if str(item.get("group_id")) == group_id:
                items_by_id.pop(item_id, None)
                delete_keys.append(item_id)

    @staticmethod
    def _find_item_by_group(
            *,
            items_by_id: Dict[str, Dict[str, Any]],
            group_id: str,
    ) -> Dict[str, Any] | None:
        for item in items_by_id.values():
            if str(item.get("group_id")) == group_id:
                return item
        return None

    def _filter_generated_items(
            self,
            *,
            generated: List[Dict[str, Any]] | None,
            group_id: str,
            items_by_id: Dict[str, Dict[str, Any]],
            delete_keys: List[str],
    ) -> List[Dict[str, Any]]:
        generated_items: List[Dict[str, Any]] = []
        for gen in generated or []:
            if gen.get("_action") in ("delete_children", "delete_group"):
                target_group_id = gen.get("group_id") or gen.get("parent_id") or group_id
                self._remove_group_items(
                    items_by_id=items_by_id,
                    group_id=str(target_group_id),
                    delete_keys=delete_keys,
                )
                continue
            if gen.get("_action") == "regenerate_children":
                self._remove_group_items(
                    items_by_id=items_by_id,
                    group_id=group_id,
                    delete_keys=delete_keys,
                )
                continue
            generated_items.append(gen)
        return generated_items

    async def _persist_working_actions(
            self,
            *,
            project_id: uuid.UUID,
            sample_id: uuid.UUID,
            user_id: uuid.UUID,
            branch_name: str,
            delete_keys: List[str],
            upserts: Dict[str, str],
            meta: Optional[Dict[str, Any]],
            mark_dirty: bool,
    ) -> Dict[str, Any]:
        redis = get_redis_client()
        key = self.working_service._build_key(project_id, sample_id, user_id, branch_name)
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
        return self.working_service._parse_hash(raw_snapshot or {})

    @staticmethod
    def _extract_action_group_id(action: Dict[str, Any]) -> str:
        group_id = action.get("group_id") or action.get("groupId")
        if not group_id:
            raise BadRequestAppException("group_id is required for sync actions")
        return str(group_id)

    def _apply_delete_action(
            self,
            *,
            group_id: str,
            items_by_id: Dict[str, Dict[str, Any]],
            delete_keys: List[str],
            sync_handler,
            context,
    ) -> None:
        existing = self._find_item_by_group(items_by_id=items_by_id, group_id=group_id)
        self._remove_group_items(
            items_by_id=items_by_id,
            group_id=group_id,
            delete_keys=delete_keys,
        )
        attrs = (existing or {}).get("attrs") or {}
        result = sync_handler.on_annotation_delete(
            annotation_id=group_id,
            attrs=attrs,
            context=context,
        )
        if result.generated:
            for gen in result.generated:
                if gen.get("_action") in ("delete_children", "delete_group"):
                    target_group_id = gen.get("group_id") or gen.get("parent_id") or group_id
                    self._remove_group_items(
                        items_by_id=items_by_id,
                        group_id=str(target_group_id),
                        delete_keys=delete_keys,
                    )
        else:
            self._remove_group_items(
                items_by_id=items_by_id,
                group_id=group_id,
                delete_keys=delete_keys,
            )

    def _apply_upsert_action(
            self,
            *,
            action: Dict[str, Any],
            action_type: str,
            group_id: str,
            project_id: uuid.UUID,
            sample_id: uuid.UUID,
            user_id: uuid.UUID,
            items_by_id: Dict[str, Dict[str, Any]],
            delete_keys: List[str],
            upserts: Dict[str, str],
            sync_handler,
            context,
    ) -> None:
        action_payload = action.get("data") or {}
        if not action_payload:
            raise BadRequestAppException("Action data is required for add/update")

        item = self._build_item_from_action(
            project_id=project_id,
            sample_id=sample_id,
            user_id=user_id,
            group_id=group_id,
            data=action_payload,
        )

        if action_type == "update":
            self._remove_group_items(
                items_by_id=items_by_id,
                group_id=group_id,
                delete_keys=delete_keys,
            )

        ann_type = self._coerce_annotation_type(item.get("type"))
        label_id = item.get("label_id")
        attrs = item.get("attrs") or {}
        geometry = item.get("geometry") or {}
        if action_type == "add":
            result = sync_handler.on_annotation_create(
                annotation_id=group_id,
                label_id=str(label_id),
                ann_type=ann_type,
                geometry=geometry,
                attrs=attrs,
                context=context,
            )
        else:
            result = sync_handler.on_annotation_update(
                annotation_id=group_id,
                label_id=str(label_id) if label_id else None,
                ann_type=ann_type,
                geometry=geometry,
                attrs=attrs,
                context=context,
            )

        item_id = str(item.get("id") or group_id)
        items_by_id[item_id] = item
        upserts[item_id] = json.dumps(item, ensure_ascii=False, default=str)

        generated_items = self._filter_generated_items(
            generated=result.generated,
            group_id=group_id,
            items_by_id=items_by_id,
            delete_keys=delete_keys,
        )
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
        items_by_id = self._index_snapshot_annotations(annotations)
        delete_keys: List[str] = []
        upserts: Dict[str, str] = {}

        for action in actions:
            action_type = action.get("type")
            if action_type not in ("add", "update", "delete"):
                raise BadRequestAppException("Invalid sync action type")
            group_id = self._extract_action_group_id(action)

            if action_type == "delete":
                self._apply_delete_action(
                    group_id=group_id,
                    items_by_id=items_by_id,
                    delete_keys=delete_keys,
                    sync_handler=sync_handler,
                    context=context,
                )
                continue

            self._apply_upsert_action(
                action=action,
                action_type=action_type,
                group_id=group_id,
                project_id=project_id,
                sample_id=sample_id,
                user_id=user_id,
                items_by_id=items_by_id,
                delete_keys=delete_keys,
                upserts=upserts,
                sync_handler=sync_handler,
                context=context,
            )

        return await self._persist_working_actions(
            project_id=project_id,
            sample_id=sample_id,
            user_id=user_id,
            branch_name=branch_name,
            delete_keys=delete_keys,
            upserts=upserts,
            meta=meta,
            mark_dirty=len(actions) > 0,
        )
