"""Query and read-model mixin for runtime service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from statistics import mean, pstdev
from typing import Any, Dict, List

from saki_api.core.exceptions import BadRequestAppException, NotFoundAppException
from saki_api.core.config import settings
from saki_api.modules.runtime.api.round_step import (
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

    async def list_step_metric_series(self, step_id: uuid.UUID, limit: int = 5000):
        await self.step_repo.get_by_id_or_raise(step_id)
        return await self.step_metric_repo.list_by_step(step_id, limit=max(1, min(limit, 100000)))

    async def list_step_candidates(self, step_id: uuid.UUID, limit: int = 200) -> List[StepCandidateItem]:
        await self.step_repo.get_by_id_or_raise(step_id)
        return await self.step_candidate_repo.list_topk_by_step(step_id, limit=max(1, min(limit, 5000)))

    async def list_step_artifacts(self, step_id: uuid.UUID) -> list[StepArtifactRead]:
        step = await self.step_repo.get_by_id_or_raise(step_id)
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
                rounds_succeeded=0,
                steps_total=0,
                steps_succeeded=0,
                metrics_latest={},
            )

        round_ids = [round_item.id for round_item in rounds]
        steps = await self.step_repo.list_by_round_ids(round_ids)
        latest_round = rounds[-1]

        return LoopSummaryStatsVO(
            rounds_total=len(rounds),
            rounds_succeeded=sum(1 for item in rounds if item.state == RoundStatus.COMPLETED),
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
            simulation_config = self._extract_simulation_config(loop.global_config or {})
            single_seed = int(simulation_config.single_seed or 0)
            strategy = str(loop.query_strategy or "")
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
        reference_simulation_config = self._extract_simulation_config(loops[0].global_config)

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
