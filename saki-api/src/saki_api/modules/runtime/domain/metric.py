import uuid
from typing import Dict

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from saki_api.modules.shared.modeling.base import UUIDMixin, OPT_JSON


class RoundSampleMetric(UUIDMixin, SQLModel, table=True):
    """
    L3 评价层：样本多维价值分数。
    """
    __tablename__ = "round_sample_metric"

    round_id: uuid.UUID = Field(foreign_key="round.id", primary_key=True)
    sample_id: uuid.UUID = Field(foreign_key="sample.id", primary_key=True)

    # 1. 主排序分值（Primary Score）
    # 无论后端算法多复杂，最后都会加权聚合出一个“采样优先级”
    # 该字段带索引，确保 20,000 条数据下 ORDER BY 的极致性能
    score: float = Field(index=True, description="综合不确定性/采样优先级")

    # 2. 多维度分值快照（Sub-metrics）
    # 存储原始的各个分量，方便前端进行散点图分析或自定义加权查询
    # 示例: {"entropy": 0.8, "diversity": 0.4, "margin": 0.1}
    extra: Dict[str, float] = Field(
        default_factory=dict,
        sa_column=Column(OPT_JSON),
        description="多维度原始分值"
    )

    # 3. 标签分布预测（可选）
    # 存储模型预测的类别概率，用于分析类别平衡
    # 示例: {"car": 0.9, "truck": 0.05}
    prediction_snapshot: Dict[str, float] = Field(
        default_factory=dict,
        sa_column=Column(OPT_JSON)
    )
