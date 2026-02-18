from __future__ import annotations

"""COCO dataset 级读写（Step 2）。"""

import json
from pathlib import Path

from saki_ir.convert.base import ERR_CONVERT_IO, ConversionContext, ConversionReport, build_batch, fail_or_report, make_report
from saki_ir.convert.coco_det import coco_to_ir, ir_to_coco
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as annotationirv1


def load_coco_dataset(
    ann_json_path: str | Path,
    image_root: str | Path | None,
    ctx: ConversionContext,
    report: ConversionReport | None = None,
) -> annotationirv1.DataBatchIR:
    """读取 COCO annotation json 并转换到 IR。"""

    report = make_report(report, strict=ctx.strict)
    path = Path(ann_json_path)

    try:
        coco = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        fail_or_report(ctx=ctx, report=report, code=ERR_CONVERT_IO, message=f"读取 COCO json 失败: {exc}", source_ref=str(path))
        return build_batch(None, None, None)
    except json.JSONDecodeError as exc:
        fail_or_report(ctx=ctx, report=report, code=ERR_CONVERT_IO, message=f"解析 COCO json 失败: {exc}", source_ref=str(path))
        return build_batch(None, None, None)

    return coco_to_ir(coco, image_root=str(image_root) if image_root is not None else None, ctx=ctx, report=report)


def save_coco_dataset(
    batch: annotationirv1.DataBatchIR,
    out_json_path: str | Path,
    image_root: str | Path | None,
    ctx: ConversionContext,
    report: ConversionReport | None = None,
) -> None:
    """将 IR 导出为 COCO annotation json。"""

    _ = image_root  # 当前仅导出 annotation json，不做图片复制。
    report = make_report(report, strict=ctx.strict)
    path = Path(out_json_path)
    coco = ir_to_coco(batch, ctx=ctx, report=report)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(coco, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        fail_or_report(ctx=ctx, report=report, code=ERR_CONVERT_IO, message=f"写入 COCO json 失败: {exc}", source_ref=str(path))
