from __future__ import annotations

from google.protobuf.json_format import MessageToDict

from saki_executor.grpc_gen import runtime_control_pb2 as pb
from saki_ir.codec import encode_payload
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as irpb
from saki_ir.transport import split_encoded_payload


def build_data_response_message(
    *,
    request_id: str,
    reply_to: str,
    step_id: str,
    query_type: int,
    items: list[pb.DataItem],
    next_cursor: str = "",
) -> pb.RuntimeMessage:
    batch = _runtime_items_to_batch(items)
    encoded = encode_payload(batch, compression_threshold=1_000_000)
    chunks = split_encoded_payload(encoded, chunk_bytes=max(1, len(encoded.payload)))
    if len(chunks) != 1:
        raise AssertionError("测试辅助预期单片 payload")
    chunk = chunks[0]
    return pb.RuntimeMessage(
        data_response=pb.DataResponse(
            request_id=request_id,
            reply_to=reply_to,
            step_id=step_id,
            query_type=query_type,
            payload_id=chunk["payload_id"],
            chunk_index=chunk["chunk_index"],
            chunk_count=chunk["chunk_count"],
            header_proto=chunk["header_proto"],
            payload_chunk=chunk["payload_chunk"],
            payload_total_size=chunk["payload_total_size"],
            payload_checksum_crc32c=chunk["payload_checksum_crc32c"],
            chunk_checksum_crc32c=chunk["chunk_checksum_crc32c"],
            next_cursor=next_cursor,
            is_last_chunk=True,
        )
    )


def _runtime_items_to_batch(items: list[pb.DataItem]) -> irpb.DataBatchIR:
    ir_items: list[irpb.DataItemIR] = []
    for item in items:
        kind = item.WhichOneof("item")
        if kind == "label_item":
            label = item.label_item
            ir_items.append(
                irpb.DataItemIR(
                    label=irpb.LabelRecord(
                        id=label.id,
                        name=label.name,
                        color=label.color,
                    )
                )
            )
            continue
        if kind == "sample_item":
            sample = item.sample_item
            record = irpb.SampleRecord(
                id=sample.id,
                asset_hash=sample.asset_hash,
                download_url=sample.download_url,
                width=int(sample.width),
                height=int(sample.height),
            )
            if sample.meta and sample.meta.ListFields():
                record.meta.CopyFrom(sample.meta)
            ir_items.append(irpb.DataItemIR(sample=record))
            continue
        if kind == "annotation_item":
            ann = item.annotation_item
            record = irpb.AnnotationRecord(
                id=ann.id,
                sample_id=ann.sample_id,
                label_id=ann.category_id,
                confidence=float(ann.confidence),
                source=_source_to_ir_enum(ann.source),
            )
            if len(ann.bbox_xywh) >= 4:
                record.geometry.rect.CopyFrom(
                    irpb.RectGeometry(
                        x=float(ann.bbox_xywh[0]),
                        y=float(ann.bbox_xywh[1]),
                        width=float(ann.bbox_xywh[2]),
                        height=float(ann.bbox_xywh[3]),
                    )
                )
            elif ann.obb and ann.obb.ListFields():
                obb = MessageToDict(ann.obb, preserving_proto_field_name=True)
                record.geometry.obb.CopyFrom(
                    irpb.ObbGeometry(
                        cx=float(obb.get("cx", 0.0)),
                        cy=float(obb.get("cy", 0.0)),
                        width=float(obb.get("width", 0.0)),
                        height=float(obb.get("height", 0.0)),
                        angle_deg_ccw=float(obb.get("angle_deg_ccw", 0.0)),
                    )
                )
            else:
                # 兼容旧测试数据：annotation 未提供几何时使用最小合法矩形。
                record.geometry.rect.CopyFrom(
                    irpb.RectGeometry(x=0.0, y=0.0, width=1.0, height=1.0)
                )
            ir_items.append(irpb.DataItemIR(annotation=record))
    return irpb.DataBatchIR(items=ir_items)


def _source_to_ir_enum(source: str) -> int:
    value = (source or "").strip().lower()
    if value == "manual":
        return irpb.ANNOTATION_SOURCE_MANUAL
    if value == "model":
        return irpb.ANNOTATION_SOURCE_MODEL
    if value == "confirmed_model":
        return irpb.ANNOTATION_SOURCE_CONFIRMED_MODEL
    if value == "system":
        return irpb.ANNOTATION_SOURCE_SYSTEM
    if value == "imported":
        return irpb.ANNOTATION_SOURCE_IMPORTED
    return irpb.ANNOTATION_SOURCE_UNSPECIFIED
