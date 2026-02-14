"""Runtime service facade composed from focused service mixins."""

from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.storage.provider import get_storage_provider
from saki_api.modules.annotation.contracts import AnnotationReadGateway
from saki_api.modules.project.contracts import ProjectReadGateway
from saki_api.modules.runtime.api.round_step import RoundCreate, RoundUpdate
from saki_api.modules.runtime.domain.round import Round
from saki_api.modules.runtime.repo.loop import LoopRepository
from saki_api.modules.runtime.repo.round import RoundRepository
from saki_api.modules.runtime.repo.runtime_executor import RuntimeExecutorRepository
from saki_api.modules.runtime.repo.step import StepRepository
from saki_api.modules.runtime.repo.step_candidate_item import StepCandidateItemRepository
from saki_api.modules.runtime.repo.step_event import StepEventRepository
from saki_api.modules.runtime.repo.step_metric_point import StepMetricPointRepository
from saki_api.modules.runtime.service.config.loop_config_service import (
    extract_model_request_config,
    merge_model_request_config,
    normalize_loop_global_config,
)
from saki_api.modules.runtime.service.runtime_service.common_mixin import RuntimeServiceCommonMixin
from saki_api.modules.runtime.service.runtime_service.loop_command_mixin import LoopCommandMixin
from saki_api.modules.runtime.service.runtime_service.query_mixin import (
    LoopSummaryStatsVO,
    RuntimeQueryMixin,
)
from saki_api.modules.runtime.service.runtime_service.round_command_mixin import RoundCommandMixin
from saki_api.modules.runtime.service.runtime_service.simulation_config_mixin import SimulationConfigMixin
from saki_api.modules.shared.application.crud_service import CrudServiceBase


class RuntimeService(
    RuntimeServiceCommonMixin,
    SimulationConfigMixin,
    LoopCommandMixin,
    RoundCommandMixin,
    RuntimeQueryMixin,
    CrudServiceBase[Round, RoundRepository, RoundCreate, RoundUpdate],
):
    RANDOM_BASELINE_STRATEGY = "random_baseline"
    _normalize_loop_global_config = staticmethod(normalize_loop_global_config)
    _merge_model_request_config = staticmethod(merge_model_request_config)
    _extract_model_request_config = staticmethod(extract_model_request_config)

    def __init__(self, session: AsyncSession):
        super().__init__(Round, RoundRepository, session)
        self.session = session
        self.project_gateway = ProjectReadGateway(session)
        self.annotation_gateway = AnnotationReadGateway(session)
        self.loop_repo = LoopRepository(session)
        self.runtime_executor_repo = RuntimeExecutorRepository(session)
        self.step_repo = StepRepository(session)
        self.step_event_repo = StepEventRepository(session)
        self.step_metric_repo = StepMetricPointRepository(session)
        self.step_candidate_repo = StepCandidateItemRepository(session)
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
