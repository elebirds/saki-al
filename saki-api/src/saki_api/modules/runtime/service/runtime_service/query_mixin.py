"""Query and read-model mixin for runtime service."""

from __future__ import annotations

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
    RoundStepArtifactsRead,
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
    async def list_loops(self, project_id: uuid.UUID) -> List[Loop]:
        return await self.loop_repo.list_by_project(project_id)

    async def list_rounds(self, loop_id: uuid.UUID, limit: int = 50) -> List[Round]:
        await self.loop_repo.get_by_id_or_raise(loop_id)
        return await self.repository.list_by_loop_desc(loop_id, limit=max(1, min(limit, 1000)))

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
    def _derive_step_event_message(*, event_type: str, payload: dict[str, Any]) -> str:
        if event_type == "log":
            return str(payload.get("message") or "")
        if event_type == "status":
            status_text = str(payload.get("status") or "").strip()
            reason_text = str(payload.get("reason") or "").strip()
            return " ".join(item for item in [status_text, reason_text] if item)
        if event_type == "progress":
            epoch = payload.get("epoch")
            step = payload.get("step")
            total_steps = payload.get("total_steps") or payload.get("totalSteps")
            return f"progress epoch={epoch} step={step}/{total_steps}"
        if event_type == "metric":
            metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
            metric_keys = ",".join(sorted(str(key) for key in metrics.keys()))
            return f"metric keys={metric_keys}"
        if event_type == "artifact":
            name = str(payload.get("name") or "").strip()
            uri = str(payload.get("uri") or "").strip()
            return " ".join(item for item in [name, uri] if item)
        try:
            return json.dumps(payload, ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(payload)

    @staticmethod
    def _derive_step_event_tags(
        *,
        event_type: str,
        payload: dict[str, Any],
        level: str | None,
        status: str | None,
        kind: str | None,
    ) -> list[str]:
        tags: list[str] = [f"event:{event_type.lower()}"]
        if level:
            tags.append(f"level:{level.upper()}")
        if status:
            tags.append(f"status:{status.lower()}")
        if kind:
            tags.append(f"kind:{kind.lower()}")
        payload_tag = payload.get("tag")
        if payload_tag is not None:
            text = str(payload_tag).strip()
            if text:
                tags.append(text)
        payload_tags = payload.get("tags")
        if isinstance(payload_tags, list):
            for item in payload_tags:
                text = str(item).strip()
                if text:
                    tags.append(text)
        deduped: list[str] = []
        seen: set[str] = set()
        for item in tags:
            lowered = str(item).strip()
            if not lowered or lowered in seen:
                continue
            deduped.append(lowered)
            seen.add(lowered)
        return deduped

    def _normalize_step_event(self, event: Any) -> dict[str, Any]:
        payload = event.payload if isinstance(event.payload, dict) else {}
        event_type = str(event.event_type or "").strip().lower() or "unknown"
        level = None
        status = None
        kind = None
        if event_type == "log":
            text = str(payload.get("level") or "").strip().upper()
            level = text or None
        if event_type == "status":
            text = str(payload.get("status") or "").strip()
            status = text or None
        if event_type == "artifact":
            text = str(payload.get("kind") or "").strip()
            kind = text or None
        tags = self._derive_step_event_tags(
            event_type=event_type,
            payload=payload,
            level=level,
            status=status,
            kind=kind,
        )
        message_text = self._derive_step_event_message(event_type=event_type, payload=payload)
        return {
            "seq": int(event.seq),
            "ts": event.ts,
            "event_type": event_type,
            "payload": payload,
            "level": level,
            "status": status,
            "kind": kind,
            "tags": tags,
            "message_text": message_text,
        }

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
                haystack = f"{item.get('message_text') or ''} {json.dumps(item.get('payload') or {}, ensure_ascii=False)}"
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

    async def list_round_artifacts(self, round_id: uuid.UUID, limit: int = 2000) -> list[RoundStepArtifactsRead]:
        steps = await self.list_steps(round_id, limit=limit)
        items: list[RoundStepArtifactsRead] = []
        for step in steps:
            artifacts = self._extract_downloadable_step_artifacts(step)
            if not artifacts:
                continue
            items.append(
                RoundStepArtifactsRead(
                    step_id=step.id,
                    step_index=int(step.step_index or 0),
                    step_type=step.step_type,
                    state=step.state,
                    artifacts=artifacts,
                )
            )
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
        latest_round = rounds[-1]

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
            metrics_latest=dict(latest_round.final_metrics or {}),
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
            final_metrics = []
            for round_item in rounds:
                m = float((round_item.final_metrics or {}).get(metric_name) or 0.0)
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
