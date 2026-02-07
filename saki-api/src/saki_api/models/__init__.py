"""
Saki API Models

This module exports all database models and schemas.

Architecture:
- Layer 1 (Physical Data): Asset, Sample, Dataset
- Layer 2 (Logical Annotation): Annotation, Commit, CommitAnnotationMap, Branch
- Layer 3 (Training Experiment): Project, TrainingJob
"""

# Enums
from saki_api.models.enums import (
    TaskType, ProjectStatus, ModelStatus, DatasetType,
    AnnotationType, AnnotationSource, TrainingJobStatus,
    ALLoopStatus, LoopRoundStatus, AnnotationBatchStatus,
)
# Layer 1: Physical Data Layer
from saki_api.models.l1.asset import Asset
from saki_api.models.l1.dataset import Dataset
from saki_api.models.l1.sample import Sample
# Layer 2: Logical Annotation Layer
from saki_api.models.l2.annotation import Annotation
from saki_api.models.l2.annotation_draft import AnnotationDraft
from saki_api.models.l2.branch import Branch
from saki_api.models.l2.camap import CommitAnnotationMap
from saki_api.models.l2.commit import Commit
from saki_api.models.l2.label import Label
from saki_api.models.l2.project import Project
# Layer 3: Training Experiment Layer
from saki_api.models.l3.job import Job
from saki_api.models.l3.loop import ALLoop
from saki_api.models.l3.metric import JobSampleMetric
from saki_api.models.l3.model import Model
from saki_api.models.l3.runtime_executor import RuntimeExecutor
from saki_api.models.l3.job_event import JobEvent
from saki_api.models.l3.job_metric_point import JobMetricPoint
from saki_api.models.l3.loop_round import LoopRound
from saki_api.models.l3.annotation_batch import AnnotationBatch, AnnotationBatchItem
# RBAC Models
from saki_api.models.rbac import (
    # Enums
    RoleType,
    ResourceType,
    Scope,
    AuditAction,
    # Role
    Role,
    RolePermission,
    # User System Role
    UserSystemRole,
    # Resource Member
    ResourceMember,
    # Audit Log
    AuditLog,
)
from saki_api.models.rbac.enums import Permissions

# User models
from saki_api.models.user import User

__all__ = [
    # Layer 1: Physical Data Layer
    "Asset", "Sample", "Dataset",

    # Layer 2: Logical Annotation Layer
    "Annotation", "AnnotationDraft", "Label",
    "Commit", "CommitAnnotationMap",
    "Branch", "Project",

    # Layer 3: Training Experiment Layer
    "Job", "ALLoop", "JobSampleMetric", "Model",
    "RuntimeExecutor", "JobEvent", "JobMetricPoint",
    "LoopRound", "AnnotationBatch", "AnnotationBatchItem",

    # Enums
    "TaskType", "ProjectStatus", "ModelStatus", "DatasetType",
    "AnnotationType", "AnnotationSource", "TrainingJobStatus",
    "ALLoopStatus", "LoopRoundStatus", "AnnotationBatchStatus",

    # User models
    "User",

    # RBAC
    "RoleType", "ResourceType", "Scope", "AuditAction",
    "Role", "RolePermission", "UserSystemRole", "ResourceMember",
    "AuditLog", "Permissions",
]
