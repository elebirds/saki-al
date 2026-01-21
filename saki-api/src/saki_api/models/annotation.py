"""
Annotation model for Git-like version control.

Annotations are immutable records with parent tracking.
Version control is managed through Commits and Branches.
---
标注 Annotation 模型，属于 L2 标注层。
标注是不可变记录，支持父标注追踪，用于版本控制。
"""
import uuid
from typing import Dict, Any, TYPE_CHECKING

from sqlalchemy import Column
from sqlmodel import Field, SQLModel, Relationship

from saki_api.models.base import TimestampMixin, UUIDMixin, OPT_JSON
from saki_api.models.enums import AnnotationType, AnnotationSource

if TYPE_CHECKING:
    from saki_api.models.label import Label


class AnnotationBase(SQLModel):
    """
    Base model for Annotation.
    Immutable annotation record with version tracking.
    """

    # 业务归属字段
    # 样本 ID：所属样本，追踪原始数据
    sample_id: uuid.UUID = Field(foreign_key="sample.id", index=True, description="ID of the sample being annotated.")
    # 标注 ID：所属标签，定义语义类别
    label_id: uuid.UUID = Field(foreign_key="label.id", index=True, description="ID of the label for this annotation.")
    # 项目 ID：所属项目，便于查询过滤
    project_id: uuid.UUID = Field(foreign_key="project.id", index=True, description="ID of the project this annotation belongs to.")

    # 视图同步字段
    # 逻辑同步 ID：用于跨视图同步同一标注
    sync_id: uuid.UUID = Field(
        index=True,
        nullable=False,
        description="Logical UUID for synchronizing annotations across views."
    )
    # 视图角色：标注所属视图角色（主视图/辅视图）
    view_role: str = Field(default="main", description="Role of the view this annotation belongs to.")
    
    # 版本控制字段
    # 血缘追踪 ID：修改时指向父标注，None 表示原始标注
    parent_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="annotation.id",
        index=True,
        description="ID of the parent annotation (for tracking modifications)."
    )
    
    # 数据描述字段
    # 标注类型：几何形状类型，决定 data 如何解析
    type: AnnotationType = Field(default=AnnotationType.RECT, index=True, description="Geometric type of the annotation (rect, obb, polygon, etc.)")
    # 标注来源
    source: AnnotationSource = Field(default=AnnotationSource.MANUAL, index=True, description="Source of annotation (MANUAL, MODEL, SYSTEM).")
    
    # 数据存储字段
    # 标注数据
    # For RECT: {x, y, width, height}
    # For OBB: {cx, cy, width, height, rotation}
    # For POLYGON/POLYLINE: {points: [[x1,y1], [x2,y2], ...]}
    data: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(OPT_JSON),
        description="The annotation geometry data."
    )
    # 扩展数据 (FEDO dual-view mapping, etc.)
    extra: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(OPT_JSON),
        description="System-specific extra data (FEDO mapping info, etc.)."
    )
    # 置信度分数
    confidence: float = Field(default=1.0, index=True, description="Confidence score of the annotation (0.0 to 1.0).", ge=0.0, le=1.0)
    
    # 审计字段
    # 标注者信息，source 决定了其解释
    annotator_id: uuid.UUID | None = Field(
        default=None,
        description="ID of the user or system that created this annotation."
    )


class Annotation(AnnotationBase, TimestampMixin, UUIDMixin, table=True):
    """
    Database model for Annotation.
    Immutable record - modifications create new annotations with parent_id reference.
    """
    __tablename__ = "annotation"

    label: "Label" = Relationship(back_populates="annotations")
