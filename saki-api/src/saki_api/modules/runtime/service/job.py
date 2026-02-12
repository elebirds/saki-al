"""Runtime JobService facade composed from focused service mixins."""

from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from saki_api.infra.storage.provider import get_storage_provider
from saki_api.modules.annotation.contracts import AnnotationReadGateway
from saki_api.modules.project.contracts import ProjectReadGateway
from saki_api.modules.runtime.api.job import JobCreate, JobUpdate
from saki_api.modules.runtime.domain.job import Job
from saki_api.modules.runtime.repo.job import JobRepository
from saki_api.modules.runtime.repo.job_task import JobTaskRepository
from saki_api.modules.runtime.repo.loop import LoopRepository
from saki_api.modules.runtime.repo.runtime_executor import RuntimeExecutorRepository
from saki_api.modules.runtime.repo.task_candidate_item import TaskCandidateItemRepository
from saki_api.modules.runtime.repo.task_event import TaskEventRepository
from saki_api.modules.runtime.repo.task_metric_point import TaskMetricPointRepository
from saki_api.modules.runtime.service.job_service.common_mixin import JobServiceCommonMixin
from saki_api.modules.runtime.service.job_service.job_command_mixin import JobCommandMixin
from saki_api.modules.runtime.service.job_service.loop_command_mixin import LoopCommandMixin
from saki_api.modules.runtime.service.job_service.query_mixin import LoopSummaryStatsVO, RuntimeQueryMixin
from saki_api.modules.runtime.service.job_service.simulation_config_mixin import SimulationConfigMixin
from saki_api.modules.runtime.service.config.loop_config_service import (
    extract_model_request_config,
    merge_model_request_config,
    normalize_loop_global_config,
)
from saki_api.modules.shared.application.crud_service import CrudServiceBase


class JobService(
    JobServiceCommonMixin,
    SimulationConfigMixin,
    LoopCommandMixin,
    JobCommandMixin,
    RuntimeQueryMixin,
    CrudServiceBase[Job, JobRepository, JobCreate, JobUpdate],
):
    RANDOM_BASELINE_STRATEGY = "random_baseline"
    _normalize_loop_global_config = staticmethod(normalize_loop_global_config)
    _merge_model_request_config = staticmethod(merge_model_request_config)
    _extract_model_request_config = staticmethod(extract_model_request_config)

    def __init__(self, session: AsyncSession):
        super().__init__(Job, JobRepository, session)
        self.session = session
        self.project_gateway = ProjectReadGateway(session)
        self.annotation_gateway = AnnotationReadGateway(session)
        self.loop_repo = LoopRepository(session)
        self.runtime_executor_repo = RuntimeExecutorRepository(session)
        self.job_task_repo = JobTaskRepository(session)
        self.task_event_repo = TaskEventRepository(session)
        self.task_metric_repo = TaskMetricPointRepository(session)
        self.task_candidate_repo = TaskCandidateItemRepository(session)
        self._storage = None

    @property
    def storage(self):
        if self._storage is None:
            self._storage = get_storage_provider()
        return self._storage


__all__ = [
    "JobService",
    "LoopSummaryStatsVO",
]
