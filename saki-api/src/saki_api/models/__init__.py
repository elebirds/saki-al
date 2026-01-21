"""
Saki API Models

This module exports all database models and schemas.

Architecture:
- Layer 1 (Physical Data): Asset, Sample, Dataset
- Layer 2 (Logical Annotation): Annotation, Commit, CommitAnnotationMap, Branch
- Layer 3 (Training Experiment): Project, TrainingJob
"""

# Layer 2: Logical Annotation Layer (Git-like version control)
from saki_api.models.annotation import Annotation, AnnotationCreate, AnnotationRead
from saki_api.models.job import (
    TrainingJob, TrainingJobCreate, TrainingJobRead, TrainingJobUpdate
)
from saki_api.models.label import Label, LabelCreate, LabelRead, LabelUpdate
from saki_api.models.model_version import ModelVersion, ModelVersionCreate, ModelVersionRead, ModelVersionUpdate
# Layer 3: Training Experiment Layer
from saki_api.models.project import (
    Project, ProjectCreate, ProjectRead, ProjectUpdate, ProjectStats,
    ProjectDataset, ProjectDatasetCreate, ProjectDatasetRead
)
from saki_api.models.version_control import (
    Commit, CommitCreate, CommitRead,
    CommitAnnotationMap, CommitAnnotationMapCreate,
    Branch, BranchCreate, BranchRead, BranchUpdate
)

# Enums
from saki_api.models.enums import (
    TaskType, ProjectStatus, ModelStatus, AnnotationSystemType,
    AnnotationType, AnnotationSource, TrainingJobStatus
)
# Layer 1: Physical Data Layer
from saki_api.models.l1.asset import Asset, AssetCreate, AssetRead
# Supporting models
from saki_api.models.l1.dataset import Dataset, DatasetCreate, DatasetRead, DatasetUpdate
from saki_api.models.l1.sample import Sample, SampleCreate, SampleRead, SampleUpdate
# RBAC Models
from saki_api.models.rbac import (
    # Enums
    RoleType,
    ResourceType,
    Scope,
    AuditAction,
    # Role
    Role,
    RoleCreate,
    RoleRead,
    RoleUpdate,
    RolePermission,
    RolePermissionCreate,
    RolePermissionRead,
    # User System Role
    UserSystemRole,
    UserSystemRoleCreate,
    UserSystemRoleRead,
    # Resource Member
    ResourceMember,
    ResourceMemberCreate,
    ResourceMemberRead,
    ResourceMemberUpdate,
    # Audit Log
    AuditLog,
    AuditLogRead,
)
from saki_api.models.rbac.enums import Permissions
# System config
from saki_api.models.system_config import (
    QueryStrategy, QueryStrategyCreate, QueryStrategyRead, QueryStrategyUpdate,
    BaseModel, BaseModelCreate, BaseModelRead, BaseModelUpdate,
)
# User models
from saki_api.models.user import User, UserCreate, UserRead, UserUpdate, UserWithPermissions, UserListItem

__all__ = [
    # Layer 1: Physical Data Layer
    "Asset", "AssetCreate", "AssetRead",
    "Sample", "SampleCreate", "SampleRead", "SampleUpdate",

    # Layer 2: Logical Annotation Layer
    "Annotation", "AnnotationCreate", "AnnotationRead",
    "Commit", "CommitCreate", "CommitRead",
    "CommitAnnotationMap", "CommitAnnotationMapCreate",
    "Branch", "BranchCreate", "BranchRead", "BranchUpdate",

    # Layer 3: Training Experiment Layer
    "Project", "ProjectCreate", "ProjectRead", "ProjectUpdate", "ProjectStats",
    "ProjectDataset", "ProjectDatasetCreate", "ProjectDatasetRead",
    "TrainingJob", "TrainingJobCreate", "TrainingJobRead", "TrainingJobUpdate",

    # Supporting models
    "Dataset", "DatasetCreate", "DatasetRead", "DatasetUpdate",
    "Label", "LabelCreate", "LabelRead", "LabelUpdate",
    "ModelVersion", "ModelVersionCreate", "ModelVersionRead", "ModelVersionUpdate",

    # Enums
    "TaskType", "ProjectStatus", "ModelStatus", "AnnotationSystemType",
    "AnnotationType", "AnnotationSource", "TrainingJobStatus",

    # User models
    "User", "UserCreate", "UserRead", "UserUpdate", "UserWithPermissions", "UserListItem",

    # RBAC
    "RoleType", "ResourceType", "Scope", "AuditAction",
    "Role", "RoleCreate", "RoleRead", "RoleUpdate",
    "RolePermission", "RolePermissionCreate", "RolePermissionRead",
    "UserSystemRole", "UserSystemRoleCreate", "UserSystemRoleRead",
    "ResourceMember", "ResourceMemberCreate", "ResourceMemberRead", "ResourceMemberUpdate",
    "AuditLog", "AuditLogRead",
    "Permissions",

    # System config
    "QueryStrategy", "QueryStrategyCreate", "QueryStrategyRead", "QueryStrategyUpdate",
    "BaseModel", "BaseModelCreate", "BaseModelRead", "BaseModelUpdate",
]
