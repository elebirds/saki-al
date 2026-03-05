"""Runtime service facade composed from focused service mixins."""

from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.storage.provider import get_storage_provider
from saki_api.modules.annotation.contracts import AnnotationReadGateway
from saki_api.modules.project.contracts import ProjectReadGateway
from saki_api.modules.runtime.api.round_step import RoundUpdate
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.repo.al_loop_visibility import ALLoopVisibilityRepository
from saki_api.modules.runtime.repo.al_round_selection_override import ALRoundSelectionOverrideRepository
from saki_api.modules.runtime.repo.al_snapshot_sample import ALSnapshotSampleRepository
from saki_api.modules.runtime.repo.al_snapshot_version import ALSnapshotVersionRepository
from saki_api.modules.runtime.repo.loop import LoopRepository
from saki_api.modules.runtime.repo.round import RoundRepository
from saki_api.modules.runtime.repo.runtime_executor import RuntimeExecutorRepository
from saki_api.modules.runtime.repo.step import StepRepository
from saki_api.modules.runtime.repo.task import TaskRepository
from saki_api.modules.runtime.repo.step_candidate_item import TaskCandidateItemRepository
from saki_api.modules.runtime.repo.step_event import TaskEventRepository
from saki_api.modules.runtime.repo.step_metric_point import TaskMetricPointRepository
from saki_api.modules.runtime.repo.prediction import PredictionRepository
from saki_api.modules.runtime.repo.prediction_binding import PredictionBindingRepository
from saki_api.modules.runtime.repo.prediction_item import PredictionItemRepository
from saki_api.modules.runtime.repo.model import ModelRepository
from saki_api.modules.runtime.repo.model_class_schema import ModelClassSchemaRepository
from saki_api.modules.runtime.repo.snapshot_query import SnapshotQueryRepository
from saki_api.modules.runtime.repo.prediction_query import PredictionQueryRepository
from saki_api.modules.runtime.service.config.loop_config_service import (
    derive_loop_max_rounds,
    derive_query_batch_size,
    extract_model_request_config,
    get_loop_global_seed,
    merge_model_request_config,
    normalize_loop_config,
)
from saki_api.modules.runtime.service.runtime_service.common_mixin import RuntimeServiceCommonMixin
from saki_api.modules.runtime.service.runtime_service.loop_gate_mixin import LoopGateMixin
from saki_api.modules.runtime.service.runtime_service.loop_command_mixin import LoopCommandMixin
from saki_api.modules.runtime.service.runtime_service.prediction_task_mixin import PredictionTaskMixin
from saki_api.modules.runtime.service.runtime_service.query_mixin import (
    LoopSummaryStatsVO,
    RuntimeQueryMixin,
)
from saki_api.modules.runtime.service.runtime_service.round_reveal_mixin import RoundRevealMixin
from saki_api.modules.runtime.service.runtime_service.round_selection_mixin import RoundSelectionMixin
from saki_api.modules.runtime.service.runtime_service.round_command_mixin import RoundCommandMixin
from saki_api.modules.runtime.service.runtime_service.simulation_config_mixin import SimulationConfigMixin
from saki_api.modules.runtime.service.runtime_service.snapshot_lifecycle_mixin import SnapshotLifecycleMixin
from saki_api.modules.runtime.service.runtime_service.snapshot_policy_mixin import SnapshotPolicyMixin
from saki_api.modules.shared.application.crud_service import CrudServiceBase


class RuntimeService(
    RuntimeServiceCommonMixin,
    SimulationConfigMixin,
    LoopCommandMixin,
    SnapshotPolicyMixin,
    SnapshotLifecycleMixin,
    RoundRevealMixin,
    RoundSelectionMixin,
    PredictionTaskMixin,
    LoopGateMixin,
    RoundCommandMixin,
    RuntimeQueryMixin,
    CrudServiceBase[Round, RoundRepository, RoundUpdate, RoundUpdate],
):
    _normalize_loop_config = staticmethod(normalize_loop_config)
    _derive_loop_max_rounds = staticmethod(derive_loop_max_rounds)
    _derive_query_batch_size = staticmethod(derive_query_batch_size)
    _merge_model_request_config = staticmethod(merge_model_request_config)
    _extract_model_request_config = staticmethod(extract_model_request_config)
    _get_loop_global_seed = staticmethod(get_loop_global_seed)

    def __init__(self, session: AsyncSession):
        super().__init__(Round, RoundRepository, session)
        self.session = session
        self.project_gateway = ProjectReadGateway(session)
        self.annotation_gateway = AnnotationReadGateway(session)
        self.loop_repo = LoopRepository(session)
        self.runtime_executor_repo = RuntimeExecutorRepository(session)
        self.step_repo = StepRepository(session)
        self.task_repo = TaskRepository(session)
        self.task_event_repo = TaskEventRepository(session)
        self.task_metric_repo = TaskMetricPointRepository(session)
        self.task_candidate_repo = TaskCandidateItemRepository(session)
        # Legacy aliases for remaining step-based mixins during migration.
        self.step_event_repo = self.task_event_repo
        self.step_metric_repo = self.task_metric_repo
        self.step_candidate_repo = self.task_candidate_repo
        self.prediction_repo = PredictionRepository(session)
        self.prediction_binding_repo = PredictionBindingRepository(session)
        self.prediction_item_repo = PredictionItemRepository(session)
        self.model_repo = ModelRepository(session)
        self.model_class_schema_repo = ModelClassSchemaRepository(session)
        self.al_snapshot_version_repo = ALSnapshotVersionRepository(session)
        self.al_snapshot_sample_repo = ALSnapshotSampleRepository(session)
        self.al_loop_visibility_repo = ALLoopVisibilityRepository(session)
        self.al_round_selection_override_repo = ALRoundSelectionOverrideRepository(session)
        self.snapshot_query_repo = SnapshotQueryRepository(session)
        self.prediction_query_repo = PredictionQueryRepository(session)
        self._storage = None

    @property
    def storage(self):
        if self._storage is None:
            self._storage = get_storage_provider()
        return self._storage


__all__ = [
    "RuntimeService",
    "LoopSummaryStatsVO",
]
