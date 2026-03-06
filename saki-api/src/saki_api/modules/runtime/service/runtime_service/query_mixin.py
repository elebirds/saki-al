"""Query and read-model mixin for runtime service."""

from __future__ import annotations

import base64
import json
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from typing import Any, Dict, List

from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.core.config import settings
from saki_api.modules.runtime.api.round_step import (
    RoundArtifactRead,
    TaskArtifactRead,
)
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.loop import Loop
from saki_api.modules.runtime.domain.task_candidate_item import TaskCandidateItem
from saki_api.modules.shared.modeling.enums import RoundStatus, StepStatus


@dataclass(slots=True)
class LoopSummaryStatsVO:
    rounds_total: int
    attempts_total: int
    rounds_succeeded: int
    steps_total: int
    steps_succeeded: int
    metrics_latest: Dict[str, Any]
    metrics_latest_train: Dict[str, Any]
    metrics_latest_eval: Dict[str, Any]
    metrics_latest_source: str


@dataclass(slots=True)
class RoundMetricViewVO:
    train_final_metrics: Dict[str, Any]
    eval_final_metrics: Dict[str, Any]
    final_metrics: Dict[str, Any]
    final_metrics_source: str


class RuntimeQueryMixin:
    _ROUND_EVENT_CURSOR_VERSION = 1
    _ROUND_EVENT_STAGE_ALLOWLIST = {"train", "eval", "score", "select", "custom"}

    @staticmethod
    def _step_type_text(step: Step) -> str:
        raw = step.step_type.value if hasattr(step.step_type, "value") else step.step_type
        return str(raw or "").strip().lower()

    @staticmethod
    def _step_sort_key(step: Step) -> tuple[int, str]:
        return int(step.step_index or 0), str(step.created_at or "")

    @staticmethod
    def _step_state_text(step: Step) -> str:
        raw = step.state.value if hasattr(step.state, "value") else step.state
        return str(raw or "").strip().lower()

    @staticmethod
    def _pick_non_empty_step_metrics(
        *,
        step: Step,
    ) -> dict[str, Any] | None:
        metrics = step.metrics if isinstance(step.metrics, dict) else {}
        if metrics:
            return dict(metrics)
        return None

    def _pick_latest_step_type_metrics(
        self,
        *,
        steps: list[Step],
        step_type: str,
    ) -> dict[str, Any]:
        if not steps:
            return {}
        ordered_steps = sorted(steps, key=self._step_sort_key)

        for require_succeeded in (True, False):
            for step in reversed(ordered_steps):
                if self._step_type_text(step) != step_type:
                    continue
                if require_succeeded and self._step_state_text(step) != "succeeded":
                    continue
                metrics = self._pick_non_empty_step_metrics(step=step)
                if metrics is not None:
                    return metrics
        return {}

    def _pick_final_metrics_with_source(
        self,
        steps: list[Step],
    ) -> tuple[dict[str, Any], str]:
        if not steps:
            return {}, "none"
        ordered_steps = sorted(steps, key=self._step_sort_key)

        for step in reversed(ordered_steps):
            if self._step_type_text(step) != "eval":
                continue
            metrics = self._pick_non_empty_step_metrics(step=step)
            if metrics is not None:
                return metrics, "eval"

        for step in reversed(ordered_steps):
            if self._step_type_text(step) != "train":
                continue
            metrics = self._pick_non_empty_step_metrics(step=step)
            if metrics is not None:
                return metrics, "train"

        for step in reversed(ordered_steps):
            metrics = self._pick_non_empty_step_metrics(step=step)
            if metrics is not None:
                return metrics, "other"
        return {}, "none"

    def _pick_final_metrics_from_steps(
        self,
        steps: list[Step],
    ) -> dict[str, Any]:
        metrics, _ = self._pick_final_metrics_with_source(steps)
        return metrics

    def derive_round_final_metrics(
        self,
        *,
        round_item: Round,
        steps: list[Step],
    ) -> dict[str, Any]:
        del round_item
        return self._pick_final_metrics_from_steps(steps)

    def derive_round_metric_view(
        self,
        *,
        round_item: Round,
        steps: list[Step],
    ) -> RoundMetricViewVO:
        del round_item
        train_final_metrics = self._pick_latest_step_type_metrics(
            steps=steps,
            step_type="train",
        )
        eval_final_metrics = self._pick_latest_step_type_metrics(
            steps=steps,
            step_type="eval",
        )
        final_metrics, final_metrics_source = self._pick_final_metrics_with_source(steps)
        return RoundMetricViewVO(
            train_final_metrics=train_final_metrics,
            eval_final_metrics=eval_final_metrics,
            final_metrics=final_metrics,
            final_metrics_source=final_metrics_source,
        )

    @staticmethod
    def _group_steps_by_round(steps: list[Step]) -> dict[uuid.UUID, list[Step]]:
        grouped: dict[uuid.UUID, list[Step]] = {}
        for step in steps:
            grouped.setdefault(step.round_id, []).append(step)
        return grouped

    async def list_loops(self, project_id: uuid.UUID) -> List[Loop]:
        return await self.loop_repo.list_by_project(project_id)

    async def list_rounds(self, loop_id: uuid.UUID, limit: int = 50) -> List[Round]:
        await self.loop_repo.get_by_id_or_raise(loop_id)
        rounds = await self.repository.list_by_loop_desc(loop_id, limit=max(1, min(limit, 1000)))
        if not rounds:
            return []
        round_ids = [row.id for row in rounds]
        steps = await self.step_repo.list_by_round_ids(round_ids)
        steps_by_round = self._group_steps_by_round(steps)
        for row in rounds:
            row.final_metrics = self.derive_round_final_metrics(
                round_item=row,
                steps=steps_by_round.get(row.id, []),
            )
        return rounds

    async def list_steps(self, round_id: uuid.UUID, limit: int = 1000) -> List[Step]:
        await self.repository.get_by_id_or_raise(round_id)
        steps = await self.step_repo.list_by_round(round_id)
        return steps[: max(1, min(limit, 5000))]

    @staticmethod
    def _derive_business_tags(*, payload: dict[str, Any]) -> list[str]:
        tags: list[str] = []

        def _push_tag(value: Any) -> None:
            text = str(value or "").strip()
            lowered = text.lower()
            if not text:
                return
            if lowered.startswith("event:") or lowered.startswith("level:") or lowered.startswith("status:"):
                return
            if lowered.startswith("kind:"):
                return
            if text in tags:
                return
            tags.append(text)

        payload_tag = payload.get("tag")
        if payload_tag is not None:
            _push_tag(payload_tag)
        payload_tags = payload.get("tags")
        if isinstance(payload_tags, list):
            for item in payload_tags:
                _push_tag(item)
        return tags

    @staticmethod
    def _derive_task_event_message_key_and_params(
        *,
        event_type: str,
        payload: dict[str, Any],
        status: str | None,
    ) -> tuple[str | None, dict[str, Any]]:
        payload_key = str(payload.get("message_key") or "").strip()
        payload_params = payload.get("message_args")
        if payload_key:
            params = payload_params if isinstance(payload_params, dict) else {}
            return payload_key, dict(params)

        if event_type == "status":
            status_key = str(status or payload.get("status") or "").strip().lower()
            if status_key:
                params: dict[str, Any] = {}
                reason = str(payload.get("reason") or "").strip()
                if reason:
                    params["reason"] = reason
                return f"runtime.status.{status_key}", params
            return "runtime.status.unknown", {}

        if event_type == "progress":
            params = {
                "epoch": int(payload.get("epoch") or 0),
                "step": int(payload.get("step") or 0),
                "total_steps": int(payload.get("total_steps") or payload.get("totalSteps") or 0),
                "eta_sec": int(payload.get("eta_sec") or payload.get("etaSec") or 0),
            }
            return "runtime.progress.update", params

        if event_type == "metric":
            metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
            metric_keys = sorted(str(key) for key in metrics.keys() if str(key).strip())
            params = {
                "step": int(payload.get("step") or 0),
                "epoch": int(payload.get("epoch") or 0),
                "metric_count": len(metric_keys),
                "metric_keys": metric_keys,
            }
            return "runtime.metric.update", params

        if event_type == "artifact":
            params = {
                "name": str(payload.get("name") or "").strip(),
                "kind": str(payload.get("kind") or "artifact").strip(),
                "uri": str(payload.get("uri") or "").strip(),
            }
            return "runtime.artifact.generated", params

        return None, {}

    @staticmethod
    def _derive_task_event_message_text(
        *,
        event_type: str,
        payload: dict[str, Any],
        status: str | None,
    ) -> str:
        if event_type == "log":
            return str(payload.get("message") or "").rstrip()
        if event_type == "status":
            status_text = str(status or payload.get("status") or "").strip().lower()
            reason_text = str(payload.get("reason") or "").strip()
            if status_text and reason_text:
                return f"{status_text}: {reason_text}"
            return status_text or reason_text
        if event_type == "progress":
            epoch = int(payload.get("epoch") or 0)
            step = int(payload.get("step") or 0)
            total_steps = int(payload.get("total_steps") or payload.get("totalSteps") or 0)
            return f"epoch {epoch}, step {step}/{total_steps}"
        if event_type == "metric":
            metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
            keys = sorted(str(key) for key in metrics.keys() if str(key).strip())
            if keys:
                preview_chunks: list[str] = []
                for key in keys[:5]:
                    raw_value = metrics.get(key)
                    try:
                        value = float(raw_value)
                        text = f"{value:.6f}".rstrip("0").rstrip(".")
                    except Exception:
                        text = str(raw_value)
                    preview_chunks.append(f"{key}={text}")
                suffix = ", ..." if len(keys) > 5 else ""
                return "metrics updated: " + ", ".join(preview_chunks) + suffix
            return "metrics updated"
        if event_type == "artifact":
            name = str(payload.get("name") or "").strip()
            uri = str(payload.get("uri") or "").strip()
            if name and uri:
                return f"{name} ({uri})"
            return name or uri
        try:
            return json.dumps(payload, ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(payload)

    def _normalize_task_event(self, event: Any) -> dict[str, Any]:
        payload = event.payload if isinstance(event.payload, dict) else {}
        event_type = str(event.event_type or "").strip().lower() or "unknown"
        level = None
        status = None
        kind = None
        raw_message = ""
        source = ""
        group_id = None
        line_count = 1
        message_key = None
        message_params: dict[str, Any] = {}
        if event_type == "log":
            text = str(payload.get("level") or "").strip().upper()
            level = text or None
            raw_message = str(payload.get("raw_message") or payload.get("message") or "")
            message_key = str(payload.get("message_key") or "").strip() or None
            message_args = payload.get("message_args")
            if isinstance(message_args, dict):
                message_params = dict(message_args)
            meta = payload.get("meta")
            if isinstance(meta, dict):
                source = str(meta.get("source") or "").strip()
                group_text = str(meta.get("group_id") or "").strip()
                if group_text:
                    group_id = group_text
                line_count_raw = meta.get("line_count")
                try:
                    line_count = max(1, int(line_count_raw or 1))
                except Exception:
                    line_count = 1
        if event_type == "status":
            text = str(payload.get("status") or "").strip()
            status = (text.lower() if text else None)
        if event_type == "artifact":
            text = str(payload.get("kind") or "").strip()
            kind = text or None
        tags = self._derive_business_tags(payload=payload)

        if not message_key:
            derived_key, derived_params = self._derive_task_event_message_key_and_params(
                event_type=event_type,
                payload=payload,
                status=status,
            )
            message_key = derived_key
            if not message_params and derived_params:
                message_params = derived_params

        message_text = self._derive_task_event_message_text(
            event_type=event_type,
            payload=payload,
            status=status,
        )
        return {
            "seq": int(event.seq),
            "ts": event.ts,
            "event_type": event_type,
            "payload": payload,
            "level": level,
            "status": status,
            "kind": kind,
            "tags": tags,
            "message_key": message_key,
            "message_params": message_params,
            "message_text": message_text,
            "raw_message": raw_message,
            "source": source or None,
            "group_id": group_id,
            "line_count": line_count,
        }

    @staticmethod
    def _round_stage_from_step_type(step_type: Any) -> str:
        value = str(step_type.value if hasattr(step_type, "value") else step_type).strip().lower()
        if value in {"train", "eval", "score", "select"}:
            return value
        return "custom"

    @staticmethod
    def _encode_round_events_cursor_payload(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=True).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")

    @staticmethod
    def _decode_round_events_cursor_payload(cursor: str) -> dict[str, Any]:
        raw_cursor = str(cursor or "").strip()
        if not raw_cursor:
            return {}
        pad = "=" * (-len(raw_cursor) % 4)
        decoded = base64.urlsafe_b64decode(f"{raw_cursor}{pad}".encode("utf-8"))
        payload = json.loads(decoded.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("cursor payload must be object")
        return payload

    def decode_round_events_cursor(self, after_cursor: str | None) -> dict[str, int]:
        raw = str(after_cursor or "").strip()
        if not raw:
            return {}
        try:
            payload = self._decode_round_events_cursor_payload(raw)
            version = int(payload.get("v", 0))
            if version != self._ROUND_EVENT_CURSOR_VERSION:
                raise ValueError("cursor version mismatch")
            task_seq_raw = payload.get("task_seq")
            if not isinstance(task_seq_raw, dict):
                raise ValueError("cursor task_seq must be object")
            task_seq: dict[str, int] = {}
            for key, value in task_seq_raw.items():
                task_id = str(uuid.UUID(str(key)))
                seq_value = max(0, int(value or 0))
                task_seq[task_id] = seq_value
            return task_seq
        except Exception as exc:
            raise BadRequestAppException("invalid after_cursor") from exc

    def encode_round_events_cursor(self, task_seq: dict[str, int]) -> str | None:
        if not task_seq:
            return None
        normalized: dict[str, int] = {}
        for key, value in task_seq.items():
            try:
                task_id = str(uuid.UUID(str(key)))
            except Exception:
                continue
            normalized[task_id] = max(0, int(value or 0))
        if not normalized:
            return None
        payload = {
            "v": self._ROUND_EVENT_CURSOR_VERSION,
            "task_seq": normalized,
        }
        return self._encode_round_events_cursor_payload(payload)

    async def query_task_events(
        self,
        *,
        task_id: uuid.UUID,
        after_seq: int = 0,
        limit: int = 5000,
        event_types: list[str] | None = None,
        levels: list[str] | None = None,
        tags: list[str] | None = None,
        q: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        include_facets: bool = False,
    ) -> dict[str, Any]:
        await self.task_repo.get_by_id_or_raise(task_id)
        normalized_event_types = [str(item).strip().lower() for item in (event_types or []) if str(item).strip()]
        normalized_levels = {str(item).strip().upper() for item in (levels or []) if str(item).strip()}
        normalized_tags = {str(item).strip().lower() for item in (tags or []) if str(item).strip()}
        text_query = str(q or "").strip().lower()
        rows = await self.task_event_repo.list_by_task_query(
            task_id=task_id,
            after_seq=max(0, int(after_seq or 0)),
            limit=max(1, min(int(limit or 5000), 100000)),
            event_types=normalized_event_types or None,
            q=text_query or None,
            from_ts=from_ts,
            to_ts=to_ts,
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            item = self._normalize_task_event(row)
            item["task_id"] = row.task_id
            if normalized_levels:
                level = str(item.get("level") or "").upper()
                if level not in normalized_levels:
                    continue
            if normalized_tags:
                row_tags = {str(tag).lower() for tag in item.get("tags") or []}
                if not row_tags.intersection(normalized_tags):
                    continue
            if text_query:
                haystack = " ".join(
                    [
                        str(item.get("message_text") or ""),
                        str(item.get("raw_message") or ""),
                        str(item.get("message_key") or ""),
                        json.dumps(item.get("payload") or {}, ensure_ascii=False),
                    ]
                )
                if text_query not in haystack.lower():
                    continue
            items.append(item)

        next_after_seq = max((int(item.get("seq") or 0) for item in items), default=None)
        payload: dict[str, Any] = {
            "items": items,
            "next_after_seq": next_after_seq,
            "facets": None,
        }
        if include_facets:
            event_type_counter: Counter[str] = Counter()
            level_counter: Counter[str] = Counter()
            tag_counter: Counter[str] = Counter()
            for item in items:
                event_type_counter[str(item.get("event_type") or "unknown")] += 1
                level_value = str(item.get("level") or "").strip()
                if level_value:
                    level_counter[level_value] += 1
                for tag in item.get("tags") or []:
                    text = str(tag).strip()
                    if text:
                        tag_counter[text] += 1
            payload["facets"] = {
                "event_types": dict(event_type_counter),
                "levels": dict(level_counter),
                "tags": dict(tag_counter),
            }
        return payload

    async def query_round_events(
        self,
        *,
        round_id: uuid.UUID,
        after_cursor: str | None = None,
        limit: int = 5000,
        stages: list[str] | None = None,
    ) -> dict[str, Any]:
        await self.repository.get_by_id_or_raise(round_id)
        all_steps = await self.step_repo.list_by_round(round_id)

        normalized_stages = [str(item or "").strip().lower() for item in (stages or []) if str(item or "").strip()]
        invalid_stages = [item for item in normalized_stages if item not in self._ROUND_EVENT_STAGE_ALLOWLIST]
        if invalid_stages:
            raise BadRequestAppException(f"invalid stages: {','.join(sorted(set(invalid_stages)))}")
        stage_filter = set(normalized_stages)

        step_stage: dict[uuid.UUID, str] = {}
        target_steps: list[Step] = []
        for step in all_steps:
            stage = self._round_stage_from_step_type(step.step_type)
            step_stage[step.id] = stage
            if stage_filter and stage not in stage_filter:
                continue
            if step.task_id is None:
                continue
            target_steps.append(step)

        cursor_task_seq = self.decode_round_events_cursor(after_cursor)
        if not target_steps:
            return {
                "items": [],
                "next_after_cursor": self.encode_round_events_cursor(cursor_task_seq) if cursor_task_seq else None,
                "has_more": False,
            }

        safe_limit = max(1, min(int(limit or 5000), 100000))
        target_task_ids = [step.task_id for step in target_steps if step.task_id is not None]
        task_seq_cursor = {
            task_id: max(0, int(cursor_task_seq.get(str(task_id), 0)))
            for task_id in target_task_ids
        }
        rows = await self.task_event_repo.list_by_round_after_cursor(
            round_id=round_id,
            task_ids=target_task_ids,
            after_task_seq=task_seq_cursor,
            limit=safe_limit,
        )

        step_lookup = {step.task_id: step for step in target_steps if step.task_id is not None}
        next_task_seq = dict(cursor_task_seq)
        items: list[dict[str, Any]] = []
        for row in rows:
            event = row[0]
            step = row[1]
            if event.task_id not in step_lookup:
                continue
            step = step_lookup[event.task_id]
            item = self._normalize_task_event(event)
            item["task_id"] = event.task_id
            item["task_index"] = int(step.step_index or 0)
            item["task_type"] = str(step.step_type.value if hasattr(step.step_type, "value") else step.step_type)
            item["step_id"] = step.id
            item["stage"] = step_stage.get(step.id) or self._round_stage_from_step_type(step.step_type)
            items.append(item)
            task_key = str(event.task_id)
            next_task_seq[task_key] = max(int(next_task_seq.get(task_key, 0) or 0), int(event.seq or 0))

        next_after = self.encode_round_events_cursor(next_task_seq)
        if not items and after_cursor:
            next_after = str(after_cursor)
        return {
            "items": items,
            "next_after_cursor": next_after,
            "has_more": len(items) >= safe_limit,
        }

    async def list_task_metric_series(self, task_id: uuid.UUID, limit: int = 5000):
        await self.task_repo.get_by_id_or_raise(task_id)
        return await self.task_metric_repo.list_by_task(task_id, limit=max(1, min(limit, 100000)))

    async def list_task_candidates(self, task_id: uuid.UUID, limit: int = 200) -> List[TaskCandidateItem]:
        await self.task_repo.get_by_id_or_raise(task_id)
        return await self.task_candidate_repo.list_topk_by_task(task_id, limit=max(1, min(limit, 5000)))

    def _extract_downloadable_step_artifacts(self, step: Step) -> list[TaskArtifactRead]:
        artifacts: list[TaskArtifactRead] = []
        for name, value in (step.artifacts or {}).items():
            if not isinstance(value, dict):
                continue
            uri = str(value.get("uri", ""))
            if not self._is_downloadable_uri(uri):
                continue
            artifacts.append(
                TaskArtifactRead(
                    name=name,
                    kind=str(value.get("kind", "artifact")),
                    uri=uri,
                    meta=value.get("meta") or {},
                )
            )
        return artifacts

    def _extract_downloadable_task_artifacts(self, task: Any) -> list[TaskArtifactRead]:
        params = task.resolved_params if isinstance(getattr(task, "resolved_params", None), dict) else {}
        artifacts_raw = params.get("_result_artifacts")
        if not isinstance(artifacts_raw, dict):
            return []

        artifacts: list[TaskArtifactRead] = []
        for name, value in artifacts_raw.items():
            if not isinstance(value, dict):
                continue
            uri = str(value.get("uri", ""))
            if not self._is_downloadable_uri(uri):
                continue
            artifacts.append(
                TaskArtifactRead(
                    name=name,
                    kind=str(value.get("kind", "artifact")),
                    uri=uri,
                    meta=value.get("meta") or {},
                )
            )
        return artifacts

    async def list_task_artifacts(self, task_id: uuid.UUID) -> list[TaskArtifactRead]:
        task = await self.task_repo.get_by_id_or_raise(task_id)
        task_artifacts = self._extract_downloadable_task_artifacts(task)
        if task_artifacts:
            return task_artifacts
        step = await self.step_repo.get_by_task_id(task_id)
        if step is None:
            return []
        return self._extract_downloadable_step_artifacts(step)

    @staticmethod
    def _artifact_stage_from_step_type(step_type: Any) -> str:
        value = str(step_type.value if hasattr(step_type, "value") else step_type).strip().lower()
        if value in {"train", "eval", "score", "select", "predict"}:
            return value
        return "custom"

    @staticmethod
    def _artifact_class_from_stage(stage: str, kind: str) -> str:
        normalized_kind = str(kind or "").strip().lower()
        if stage == "train":
            return "model_artifact"
        if stage == "eval":
            return "eval_artifact"
        if stage in {"score", "select"}:
            return "selection_artifact"
        if stage == "predict":
            return "prediction_artifact"
        if normalized_kind in {"report", "eval_artifact"}:
            return "eval_artifact"
        return "generic_artifact"

    async def list_round_artifacts(self, round_id: uuid.UUID, limit: int = 2000) -> list[RoundArtifactRead]:
        steps = await self.list_steps(round_id, limit=limit)
        items: list[RoundArtifactRead] = []
        for step in steps:
            artifacts = self._extract_downloadable_step_artifacts(step)
            if not artifacts:
                continue
            stage = self._artifact_stage_from_step_type(step.step_type)
            for artifact in artifacts:
                size_raw = (artifact.meta or {}).get("size") if isinstance(artifact.meta, dict) else None
                size_value = int(size_raw) if isinstance(size_raw, (int, float)) else None
                items.append(
                    RoundArtifactRead(
                        step_id=step.id,
                        task_id=step.task_id,
                        step_index=int(step.step_index or 0),
                        stage=stage,
                        artifact_class=self._artifact_class_from_stage(stage, artifact.kind),
                        name=artifact.name,
                        kind=artifact.kind,
                        uri=artifact.uri,
                        size=size_value,
                        created_at=step.updated_at,
                    )
                )
        items.sort(key=lambda item: (int(item.step_index or 0), str(item.name or "")))
        return items

    def _resolve_artifact_download_url_from_step(
        self,
        *,
        step: Step,
        artifact_name: str,
        expires_in_hours: int = 2,
    ) -> str:
        artifact = (step.artifacts or {}).get(artifact_name)
        if not artifact:
            raise NotFoundAppException(f"Artifact {artifact_name} not found")
        if not isinstance(artifact, dict):
            raise BadRequestAppException("Artifact payload is invalid")

        uri = str(artifact.get("uri") or "")
        if not uri:
            raise BadRequestAppException("Artifact URI is empty")

        return self._resolve_artifact_download_url_from_uri(uri=uri, expires_in_hours=expires_in_hours)

    def _resolve_artifact_download_url_from_uri(
        self,
        *,
        uri: str,
        expires_in_hours: int = 2,
    ) -> str:
        uri = str(uri or "").strip()
        if not uri:
            raise BadRequestAppException("Artifact URI is empty")

        if uri.startswith("s3://"):
            _, _, bucket_and_path = uri.partition("s3://")
            _, _, object_path = bucket_and_path.partition("/")
            if not object_path:
                raise BadRequestAppException(f"Invalid S3 URI: {uri}")
            return self.storage.get_presigned_url(
                object_name=object_path,
                expires_delta=timedelta(hours=expires_in_hours),
            )

        if uri.startswith("http://") or uri.startswith("https://"):
            return uri

        raise BadRequestAppException(f"Unsupported artifact URI: {uri}")

    async def get_task_artifact_download_url(
        self,
        *,
        task_id: uuid.UUID,
        artifact_name: str,
        expires_in_hours: int = 2,
    ) -> str:
        task = await self.task_repo.get_by_id_or_raise(task_id)
        params = task.resolved_params if isinstance(getattr(task, "resolved_params", None), dict) else {}
        artifacts_raw = params.get("_result_artifacts")
        if isinstance(artifacts_raw, dict):
            artifact = artifacts_raw.get(artifact_name)
            if isinstance(artifact, dict):
                return self._resolve_artifact_download_url_from_uri(
                    uri=str(artifact.get("uri") or ""),
                    expires_in_hours=expires_in_hours,
                )

        step = await self.step_repo.get_by_task_id(task_id)
        if step is None:
            raise NotFoundAppException(f"Task {task_id} has no downloadable artifacts")
        return self._resolve_artifact_download_url_from_step(
            step=step,
            artifact_name=artifact_name,
            expires_in_hours=expires_in_hours,
        )

    async def summarize_loop(self, loop_id: uuid.UUID) -> LoopSummaryStatsVO:
        await self.loop_repo.get_by_id_or_raise(loop_id)

        rounds = await self.repository.list_by_loop(loop_id)
        if not rounds:
            return LoopSummaryStatsVO(
                rounds_total=0,
                attempts_total=0,
                rounds_succeeded=0,
                steps_total=0,
                steps_succeeded=0,
                metrics_latest={},
                metrics_latest_train={},
                metrics_latest_eval={},
                metrics_latest_source="none",
            )

        round_ids = [round_item.id for round_item in rounds]
        steps = await self.step_repo.list_by_round_ids(round_ids)
        latest_round = rounds[-1]
        steps_by_round = self._group_steps_by_round(steps)
        latest_round_metric_view = self.derive_round_metric_view(
            round_item=latest_round,
            steps=steps_by_round.get(latest_round.id, []),
        )

        logical_round_ids = {int(item.round_index) for item in rounds}
        succeeded_logical_round_ids = {
            int(item.round_index) for item in rounds if item.state == RoundStatus.COMPLETED
        }

        return LoopSummaryStatsVO(
            rounds_total=len(logical_round_ids),
            attempts_total=len(rounds),
            rounds_succeeded=len(succeeded_logical_round_ids),
            steps_total=len(steps),
            steps_succeeded=sum(1 for item in steps if item.state == StepStatus.SUCCEEDED),
            metrics_latest=latest_round_metric_view.final_metrics,
            metrics_latest_train=latest_round_metric_view.train_final_metrics,
            metrics_latest_eval=latest_round_metric_view.eval_final_metrics,
            metrics_latest_source=latest_round_metric_view.final_metrics_source,
        )
