from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OrientedRCNNConfig:
    """插件配置解析后的强类型对象。"""

    epochs: int
    batch: int
    imgsz: int
    workers: int
    predict_conf: float
    val_split_ratio: float

    model_source: str
    model_preset: str
    model_custom_ref: str

    nms_iou_thr: float
    max_per_img: int
    predict_geometry_mode: str
    device: str

    # 由上游 runtime 注入，用于几何输出策略自动决策
    annotation_types: tuple[str, ...]

    # 运行时可复现性参数
    split_seed: int
    train_seed: int
    sampling_seed: int
    round_index: int
    deterministic: bool


@dataclass(frozen=True)
class PreparedDataset:
    """prepare_data 结束后写入磁盘的数据集摘要。"""

    train_ids: set[str]
    val_ids: set[str]
    val_degraded: bool
    classes: tuple[str, ...]
    class_name_map: dict[str, str]
    manifest: dict[str, Any]


@dataclass(frozen=True)
class TrainRuntimeConfig:
    """训练阶段真实执行参数（已绑定模型和设备）。"""

    device: str
    model_ref: str
    config_path: Path
    work_dir: Path
    max_epochs: int


@dataclass(frozen=True)
class EvalRuntimeConfig:
    """评估阶段真实执行参数。"""

    device: str
    model_ref: str
    config_path: Path
    work_dir: Path


@dataclass(frozen=True)
class DetectionPrediction:
    """单个预测框的规范化结果。

    说明：
    - rbox 仅供插件内部算法（如 aug_iou）使用，不会直接外发给 API。
    - candidate 输出时只会带 geometry/class/confidence 等 IR 规范字段。
    """

    class_index: int
    class_name: str
    confidence: float
    geometry: dict[str, Any]
    rbox: tuple[float, float, float, float, float] | None = None


@dataclass(frozen=True)
class CanonicalMetrics:
    """满足 SDK metric contract 的规范指标。"""

    map50: float
    map50_95: float
    precision: float
    recall: float
    loss: float | None = None

    def to_train_metrics(self) -> dict[str, float]:
        return {
            "map50": float(self.map50),
            "map50_95": float(self.map50_95),
            "precision": float(self.precision),
            "recall": float(self.recall),
            "loss": float(self.loss or 0.0),
        }

    def to_eval_metrics(self) -> dict[str, float]:
        return {
            "map50": float(self.map50),
            "map50_95": float(self.map50_95),
            "precision": float(self.precision),
            "recall": float(self.recall),
        }
