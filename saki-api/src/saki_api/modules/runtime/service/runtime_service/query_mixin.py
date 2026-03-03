"""Query and read-model mixin for runtime service."""

from __future__ import annotations

import base64
import json
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from statistics import mean, pstdev
from typing import Any, Dict, List

from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.core.config import settings
from saki_api.modules.runtime.api.round_step import (
    RoundArtifactRead,
    SimulationComparisonRead,
    SimulationCurvePointRead,
    SimulationStrategySummaryRead,
    StepArtifactRead,
)
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.domain.step import Step
from saki_api.modules.runtime.domain.loop import Loop
from saki_api.modules.runtime.domain.step_candidate_item import StepCandidateItem
from saki_api.modules.shared.modeling.enums import RoundStatus, StepStatus


@dataclass(slots=True)
class LoopSummaryStatsVO:
    rounds_total: int
    attempts_total: int
    rounds_succeeded: int
    steps_total: int
    steps_succeeded: int
    metrics_latest: Dict[str, Any]


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
    def _pick_non_empty_step_metrics(
        *,
        step: Step,
        metric_series_latest_by_step: dict[uuid.UUID, dict[str, float]] | None = None,
    ) -> dict[str, Any] | None:
        metrics = step.metrics if isinstance(step.metrics, dict) else {}
        if metrics:
            return dict(metrics)
        if metric_series_latest_by_step:
            series_metrics = metric_series_latest_by_step.get(step.id) or {}
            if series_metrics:
                return dict(series_metrics)
        return None

    def _pick_final_metrics_from_steps(
        self,
        steps: list[Step],
        *,
        metric_series_latest_by_step: dict[uuid.UUID, dict[str, float]] | None = None,
    ) -> dict[str, Any]:
        if not steps:
            return {}
        ordered_steps = sorted(steps, key=self._step_sort_key)

        for step in reversed(ordered_steps):
            if self._step_type_text(step) != "eval":
                continue
            metrics = self._pick_non_empty_step_metrics(
                step=step,
                metric_series_latest_by_step=metric_series_latest_by_step,
            )
            if metrics is not None:
                return metrics

        for step in reversed(ordered_steps):
            if self._step_type_text(step) != "train":
                continue
            metrics = self._pick_non_empty_step_metrics(
                step=step,
                metric_series_latest_by_step=metric_series_latest_by_step,
            )
            if metrics is not None:
                return metrics

        for step in reversed(ordered_steps):
            metrics = self._pick_non_empty_step_metrics(
                step=step,
                metric_series_latest_by_step=metric_series_latest_by_step,
            )
            if metrics is not None:
                return metrics
        return {}

    async def build_metric_series_latest_by_step(
        self,
        *,
        steps: list[Step],
    ) -> dict[uuid.UUID, dict[str, float]]:
        step_ids = [step.id for step in steps]
        if not step_ids:
            return {}
        return await self.step_metric_repo.latest_metrics_by_step_ids(step_ids)

    def derive_round_final_metrics(
        self,
        *,
        round_item: Round,
        steps: list[Step],
        metric_series_latest_by_step: dict[uuid.UUID, dict[str, float]] | None = None,
    ) -> dict[str, Any]:
        derived = self._pick_final_metrics_from_steps(
            steps,
            metric_series_latest_by_step=metric_series_latest_by_step,
        )
        if derived:
            return derived
        existing = round_item.final_metrics if isinstance(round_item.final_metrics, dict) else {}
        return dict(existing)

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
        metric_series_latest_by_step = await self.build_metric_series_latest_by_step(steps=steps)
        steps_by_round = self._group_steps_by_round(steps)
        for row in rounds:
            row.final_metrics = self.derive_round_final_metrics(
                round_item=row,
                steps=steps_by_round.get(row.id, []),
                metric_series_latest_by_step=metric_series_latest_by_step,
            )
        return rounds

    async def list_steps(self, round_id: uuid.UUID, limit: int = 1000) -> List[Step]:
        await self.repository.get_by_id_or_raise(round_id)
        steps = await self.step_repo.list_by_round(round_id)
        return steps[: max(1, min(limit, 5000))]

    async def list_step_events(self, step_id: uuid.UUID, after_seq: int = 0, limit: int = 5000):
        await self.step_repo.get_by_id_or_raise(step_id)
        return await self.step_event_repo.list_by_step_after_seq(
            step_id=step_id,
            after_seq=max(0, after_seq),
            limit=max(1, min(limit, 100000)),
        )

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
    def _derive_step_event_message_key_and_params(
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
    def _derive_step_event_message_text(
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
                preview = ", ".join(keys[:4])
                suffix = "..." if len(keys) > 4 else ""
                return f"metrics updated ({preview}{suffix})"
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

    def _normalize_step_event(self, event: Any) -> dict[str, Any]:
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
            derived_key, derived_params = self._derive_step_event_message_key_and_params(
                event_type=event_type,
                payload=payload,
                status=status,
            )
            message_key = derived_key
            if not message_params and derived_params:
                message_params = derived_params

        message_text = self._derive_step_event_message_text(
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
            step_seq_raw = payload.get("step_seq")
            if not isinstance(step_seq_raw, dict):
                raise ValueError("cursor step_seq must be object")
            step_seq: dict[str, int] = {}
            for key, value in step_seq_raw.items():
                step_id = str(uuid.UUID(str(key)))
                seq_value = max(0, int(value or 0))
                step_seq[step_id] = seq_value
            return step_seq
        except Exception as exc:
            raise BadRequestAppException("invalid after_cursor") from exc

    def encode_round_events_cursor(self, step_seq: dict[str, int]) -> str | None:
        if not step_seq:
            return None
        normalized: dict[str, int] = {}
        for key, value in step_seq.items():
            try:
                step_id = str(uuid.UUID(str(key)))
            except Exception:
                continue
            normalized[step_id] = max(0, int(value or 0))
        if not normalized:
            return None
        payload = {
            "v": self._ROUND_EVENT_CURSOR_VERSION,
            "step_seq": normalized,
        }
        return self._encode_round_events_cursor_payload(payload)

    async def query_step_events(
        self,
        *,
        step_id: uuid.UUID,
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
        await self.step_repo.get_by_id_or_raise(step_id)
        normalized_event_types = [str(item).strip().lower() for item in (event_types or []) if str(item).strip()]
        normalized_levels = {str(item).strip().upper() for item in (levels or []) if str(item).strip()}
        normalized_tags = {str(item).strip().lower() for item in (tags or []) if str(item).strip()}
        text_query = str(q or "").strip().lower()
        rows = await self.step_event_repo.list_by_step_query(
            step_id=step_id,
            after_seq=max(0, int(after_seq or 0)),
            limit=max(1, min(int(limit or 5000), 100000)),
            event_types=normalized_event_types or None,
            q=text_query or None,
            from_ts=from_ts,
            to_ts=to_ts,
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            item = self._normalize_step_event(row)
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
            target_steps.append(step)

        cursor_step_seq = self.decode_round_events_cursor(after_cursor)
        if not target_steps:
            return {
                "items": [],
                "next_after_cursor": self.encode_round_events_cursor(cursor_step_seq) if cursor_step_seq else None,
                "has_more": False,
            }

        safe_limit = max(1, min(int(limit or 5000), 100000))
        target_step_ids = [step.id for step in target_steps]
        step_seq_cursor = {step_id: max(0, int(cursor_step_seq.get(str(step_id), 0))) for step_id in target_step_ids}
        rows = await self.step_event_repo.list_by_round_after_cursor(
            round_id=round_id,
            step_ids=target_step_ids,
            after_step_seq=step_seq_cursor,
            limit=safe_limit,
        )

        step_lookup = {step.id: step for step in target_steps}
        next_step_seq = dict(cursor_step_seq)
        items: list[dict[str, Any]] = []
        for row in rows:
            event = row[0]
            step = row[1]
            if step.id not in step_lookup:
                continue
            item = self._normalize_step_event(event)
            item["step_id"] = step.id
            item["step_index"] = int(step.step_index or 0)
            item["step_type"] = str(step.step_type.value if hasattr(step.step_type, "value") else step.step_type)
            item["stage"] = step_stage.get(step.id) or self._round_stage_from_step_type(step.step_type)
            items.append(item)
            step_key = str(step.id)
            next_step_seq[step_key] = max(int(next_step_seq.get(step_key, 0) or 0), int(event.seq or 0))

        next_after = self.encode_round_events_cursor(next_step_seq)
        if not items and after_cursor:
            next_after = str(after_cursor)
        return {
            "items": items,
            "next_after_cursor": next_after,
            "has_more": len(items) >= safe_limit,
        }

    async def list_step_metric_series(self, step_id: uuid.UUID, limit: int = 5000):
        await self.step_repo.get_by_id_or_raise(step_id)
        return await self.step_metric_repo.list_by_step(step_id, limit=max(1, min(limit, 100000)))

    async def list_step_candidates(self, step_id: uuid.UUID, limit: int = 200) -> List[StepCandidateItem]:
        await self.step_repo.get_by_id_or_raise(step_id)
        return await self.step_candidate_repo.list_topk_by_step(step_id, limit=max(1, min(limit, 5000)))

    def _extract_downloadable_step_artifacts(self, step: Step) -> list[StepArtifactRead]:
        artifacts: list[StepArtifactRead] = []
        for name, value in (step.artifacts or {}).items():
            if not isinstance(value, dict):
                continue
            uri = str(value.get("uri", ""))
            if not self._is_downloadable_uri(uri):
                continue
            artifacts.append(
                StepArtifactRead(
                    name=name,
                    kind=str(value.get("kind", "artifact")),
                    uri=uri,
                    meta=value.get("meta") or {},
                )
            )
        return artifacts

    async def list_step_artifacts(self, step_id: uuid.UUID) -> list[StepArtifactRead]:
        step = await self.step_repo.get_by_id_or_raise(step_id)
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

    async def get_step_artifact_download_url(
        self,
        *,
        step_id: uuid.UUID,
        artifact_name: str,
        expires_in_hours: int = 2,
    ) -> str:
        step = await self.step_repo.get_by_id_or_raise(step_id)
        artifact = (step.artifacts or {}).get(artifact_name)
        if not artifact:
            raise NotFoundAppException(f"Artifact {artifact_name} not found")
        if not isinstance(artifact, dict):
            raise BadRequestAppException("Artifact payload is invalid")

        uri = str(artifact.get("uri") or "")
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
            )

        round_ids = [round_item.id for round_item in rounds]
        steps = await self.step_repo.list_by_round_ids(round_ids)
        metric_series_latest_by_step = await self.build_metric_series_latest_by_step(steps=steps)
        latest_round = rounds[-1]
        steps_by_round = self._group_steps_by_round(steps)
        latest_round_metrics = self.derive_round_final_metrics(
            round_item=latest_round,
            steps=steps_by_round.get(latest_round.id, []),
            metric_series_latest_by_step=metric_series_latest_by_step,
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
            metrics_latest=latest_round_metrics,
        )

    async def get_simulation_experiment_comparison(
        self,
        *,
        experiment_group_id: uuid.UUID,
        metric_name: str = "map50",
    ) -> SimulationComparisonRead:
        loops = await self.loop_repo.list_by_experiment_group(experiment_group_id)
        if not loops:
            raise NotFoundAppException(f"Simulation experiment {experiment_group_id} not found")

        by_strategy: dict[str, dict[int, list[tuple[int, float]]]] = {}
        summary_rows: dict[str, list[tuple[int, float]]] = {}

        for loop in loops:
            simulation_config = self._extract_simulation_config(loop.config or {})
            single_seed = int(simulation_config.single_seed or 0)
            loop_sampling = loop.config.get("sampling") if isinstance(loop.config, dict) else {}
            strategy = str((loop_sampling or {}).get("strategy") or self.RANDOM_BASELINE_STRATEGY)
            strategy_data = by_strategy.setdefault(strategy, {})

            rounds = await self.repository.list_by_loop(loop.id)
            round_ids = [round_item.id for round_item in rounds]
            steps = await self.step_repo.list_by_round_ids(round_ids)
            metric_series_latest_by_step = await self.build_metric_series_latest_by_step(steps=steps)
            steps_by_round = self._group_steps_by_round(steps)
            final_metrics = []
            for round_item in rounds:
                effective_metrics = self.derive_round_final_metrics(
                    round_item=round_item,
                    steps=steps_by_round.get(round_item.id, []),
                    metric_series_latest_by_step=metric_series_latest_by_step,
                )
                m = float((effective_metrics or {}).get(metric_name) or 0.0)
                final_metrics.append((round_item.round_index, m))
                strategy_data.setdefault(round_item.round_index, []).append((single_seed, m))

            if final_metrics:
                aulc = mean([row[1] for row in final_metrics])
                summary_rows.setdefault(strategy, []).append((single_seed, aulc))

        curves: list[SimulationCurvePointRead] = []
        summaries: list[SimulationStrategySummaryRead] = []

        if not by_strategy:
            return SimulationComparisonRead(
                experiment_group_id=experiment_group_id,
                metric_name=metric_name,
                curves=[],
                strategies=[],
                baseline_strategy=self.RANDOM_BASELINE_STRATEGY,
                delta_vs_baseline={},
            )

        baseline = self.RANDOM_BASELINE_STRATEGY if self.RANDOM_BASELINE_STRATEGY in by_strategy else list(by_strategy)[0]

        baseline_final_mean = 0.0
        if baseline in by_strategy:
            baseline_rounds = sorted(by_strategy[baseline].items(), key=lambda item: item[0])
            if baseline_rounds:
                baseline_last_values = [row[1] for _, rows in baseline_rounds for row in rows]
                baseline_final_mean = mean(baseline_last_values) if baseline_last_values else 0.0

        delta_vs_baseline: dict[str, float] = {}
        reference_simulation_config = self._extract_simulation_config(loops[0].config or {})

        for strategy, round_map in sorted(by_strategy.items(), key=lambda item: item[0]):
            rounds_sorted = sorted(round_map.items(), key=lambda item: item[0])
            for round_index, items in rounds_sorted:
                values = [row[1] for row in items]
                target_ratio = round(
                    min(
                        1.0,
                        reference_simulation_config.seed_ratio + round_index * reference_simulation_config.step_ratio,
                    ),
                    6,
                )
                curves.append(
                    SimulationCurvePointRead(
                        strategy=strategy,
                        round_index=int(round_index),
                        target_ratio=target_ratio,
                        mean_metric=float(mean(values) if values else 0.0),
                        std_metric=float(pstdev(values) if len(values) > 1 else 0.0),
                    )
                )

            final_values = [items[-1][1] for _, items in rounds_sorted if items]
            aulc_values = [row[1] for row in summary_rows.get(strategy, [])]
            final_mean = float(mean(final_values) if final_values else 0.0)
            summaries.append(
                SimulationStrategySummaryRead(
                    strategy=strategy,
                    seeds=[seed for seed, _ in summary_rows.get(strategy, [])],
                    final_mean=final_mean,
                    final_std=float(pstdev(final_values) if len(final_values) > 1 else 0.0),
                    aulc_mean=float(mean(aulc_values) if aulc_values else 0.0),
                )
            )
            delta_vs_baseline[strategy] = final_mean - baseline_final_mean

        return SimulationComparisonRead(
            experiment_group_id=experiment_group_id,
            metric_name=metric_name,
            curves=curves,
            strategies=summaries,
            baseline_strategy=baseline,
            delta_vs_baseline=delta_vs_baseline,
        )
