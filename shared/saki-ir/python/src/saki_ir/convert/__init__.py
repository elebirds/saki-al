from __future__ import annotations

from saki_ir.convert.base import (
    ERR_CONVERT_GEOMETRY,
    ERR_CONVERT_IO,
    ERR_CONVERT_SCHEMA,
    ERR_CONVERT_UNSUPPORTED,
    ConversionContext,
    ConversionError,
    ConversionReport,
    build_batch,
    clip_tlwh_to_image,
    dict_to_struct,
    maybe_clip_rect,
    rect_ir_to_yolo,
    require_single_sample,
    split_batch,
    struct_to_dict,
    tlbr_to_tlwh,
    tlwh_to_tlbr,
    yolo_to_rect_ir,
)
from saki_ir.convert.coco_det import coco_to_ir, ir_to_coco
from saki_ir.convert.dota_obb import dota_txt_to_ir, ir_to_dota_txt
from saki_ir.convert.voc_det import ir_to_voc_xml, voc_xml_to_ir
from saki_ir.convert.yolo_det import ir_to_yolo_txt, yolo_txt_to_ir
from saki_ir.convert.yolo_obb import ir_to_yolo_obb_txt, yolo_obb_txt_to_ir

__all__ = [
    "ERR_CONVERT_SCHEMA",
    "ERR_CONVERT_IO",
    "ERR_CONVERT_GEOMETRY",
    "ERR_CONVERT_UNSUPPORTED",
    "ConversionContext",
    "ConversionError",
    "ConversionReport",
    "dict_to_struct",
    "struct_to_dict",
    "tlwh_to_tlbr",
    "tlbr_to_tlwh",
    "rect_ir_to_yolo",
    "yolo_to_rect_ir",
    "clip_tlwh_to_image",
    "build_batch",
    "split_batch",
    "require_single_sample",
    "maybe_clip_rect",
    "coco_to_ir",
    "ir_to_coco",
    "dota_txt_to_ir",
    "ir_to_dota_txt",
    "voc_xml_to_ir",
    "ir_to_voc_xml",
    "yolo_txt_to_ir",
    "ir_to_yolo_txt",
    "yolo_obb_txt_to_ir",
    "ir_to_yolo_obb_txt",
]
