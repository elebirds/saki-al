"""Saki API models export hub."""

from saki_api.models.access import User
from saki_api.models.annotation import Annotation, AnnotationDraft, CommitAnnotationMap
from saki_api.models.enums import (
    ALLoopMode,
    ALLoopStatus,
    AnnotationSource,
    AnnotationType,
    CommitSampleReviewState,
    DatasetType,
    JobStatusV2,
    JobTaskStatus,
    JobTaskType,
    LoopPhase,
    LoopRoundStatus,
    ModelStatus,
    ProjectStatus,
    TaskType,
    TrainingJobStatus,
)
from saki_api.models.project import Branch, Commit, CommitSampleState, Label, Project
from saki_api.models.rbac import (
    AuditAction,
    AuditLog,
    ResourceMember,
    ResourceType,
    Role,
    RolePermission,
    RoleType,
    Scope,
    UserSystemRole,
)
from saki_api.models.rbac.enums import Permissions
from saki_api.models.runtime import (
    ALLoop,
    Job,
    JobSampleMetric,
    JobTask,
    Model,
    RuntimeExecutor,
    RuntimeExecutorStats,
    TaskCandidateItem,
    TaskEvent,
    TaskMetricPoint,
)
from saki_api.models.storage import Asset, Dataset, Sample
from saki_api.models.system import SystemSetting

__all__ = [
    # Storage
    "Asset", "Sample", "Dataset",

    # Annotation and project
    "Annotation", "AnnotationDraft", "Label",
    "Commit", "CommitAnnotationMap", "CommitSampleState",
    "Branch", "Project",

    # Runtime
    "Job", "ALLoop", "JobSampleMetric", "Model",
    "RuntimeExecutor", "RuntimeExecutorStats",
    "JobTask", "TaskEvent", "TaskMetricPoint", "TaskCandidateItem",
    "SystemSetting",

    # Enums
    "TaskType", "ProjectStatus", "ModelStatus", "DatasetType",
    "AnnotationType", "AnnotationSource", "TrainingJobStatus",
    "ALLoopStatus", "ALLoopMode", "LoopRoundStatus",
    "LoopPhase", "JobStatusV2", "JobTaskType", "JobTaskStatus", "CommitSampleReviewState",

    # Access
    "User",

    # RBAC
    "RoleType", "ResourceType", "Scope", "AuditAction",
    "Role", "RolePermission", "UserSystemRole", "ResourceMember",
    "AuditLog", "Permissions",
]
