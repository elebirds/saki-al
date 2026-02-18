from __future__ import annotations

"""Detection 数据集级 IO API。"""

from saki_ir.convert.io.coco_io import load_coco_dataset, save_coco_dataset
from saki_ir.convert.io.voc_io import load_voc_dataset, save_voc_dataset
from saki_ir.convert.io.yolo_io import load_yolo_dataset, save_yolo_dataset

__all__ = [
    "load_coco_dataset",
    "save_coco_dataset",
    "load_voc_dataset",
    "save_voc_dataset",
    "load_yolo_dataset",
    "save_yolo_dataset",
]
