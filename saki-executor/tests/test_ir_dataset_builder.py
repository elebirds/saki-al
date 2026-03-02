from saki_executor.steps.services.ir_dataset_builder import build_training_batch_ir
from saki_ir.proto.saki.ir.v1 import annotation_ir_pb2 as irpb


def test_build_training_batch_ir_supports_legacy_absolute_obb_payload():
    batch, report = build_training_batch_ir(
        labels=[{"id": "label-1", "name": "ship"}],
        samples=[
            {
                "id": "sample-1",
                "width": 1000,
                "height": 500,
                "meta": {"scene": "harbor"},
                "local_path": "/tmp/sample-1.jpg",
            }
        ],
        annotations=[
            {
                "id": "ann-1",
                "sample_id": "sample-1",
                "category_id": "label-1",
                "source": "manual",
                "confidence": 0.8,
                "obb": {
                    "cx": 512.0,
                    "cy": 256.0,
                    "width": 400.0,
                    "height": 200.0,
                    "angle_deg_ccw": 30.0,
                },
            }
        ],
    )

    assert report.label_count == 1
    assert report.sample_count == 1
    assert report.annotation_count == 1
    assert report.dropped_annotation_count == 0

    sample_items = [item.sample for item in batch.items if item.WhichOneof("item") == "sample"]
    assert len(sample_items) == 1
    runtime_meta = sample_items[0].meta.fields["runtime"].struct_value
    assert runtime_meta.fields["local_path"].string_value == "/tmp/sample-1.jpg"

    annotation_items = [item.annotation for item in batch.items if item.WhichOneof("item") == "annotation"]
    assert len(annotation_items) == 1
    ann = annotation_items[0]
    assert ann.geometry.HasField("obb")
    assert ann.geometry.obb.width == 400.0
    assert ann.geometry.obb.height == 200.0
    assert ann.geometry.obb.angle_deg_ccw == 30.0


def test_build_training_batch_ir_converts_normalized_obb_to_absolute_geometry():
    batch, report = build_training_batch_ir(
        labels=[{"id": "label-1", "name": "ship"}],
        samples=[{"id": "sample-1", "width": 1000, "height": 500}],
        annotations=[
            {
                "sample_id": "sample-1",
                "category_id": "label-1",
                "obb": {
                    "cx": 0.5,
                    "cy": 0.25,
                    "w": 0.4,
                    "h": 0.2,
                    "angle_deg": 15.0,
                    "normalized": True,
                },
            }
        ],
    )

    assert report.annotation_count == 1
    ann = next(item.annotation for item in batch.items if item.WhichOneof("item") == "annotation")
    assert ann.geometry.HasField("obb")
    assert ann.geometry.obb.cx == 500.0
    assert ann.geometry.obb.cy == 125.0
    assert ann.geometry.obb.width == 400.0
    assert ann.geometry.obb.height == 100.0
    assert ann.geometry.obb.angle_deg_ccw == 15.0


def test_build_training_batch_ir_maps_confirmed_model_source():
    batch, report = build_training_batch_ir(
        labels=[{"id": "label-1", "name": "ship"}],
        samples=[{"id": "sample-1", "width": 640, "height": 480}],
        annotations=[
            {
                "id": "ann-1",
                "sample_id": "sample-1",
                "category_id": "label-1",
                "bbox_xywh": [12.0, 20.0, 30.0, 40.0],
                "source": "confirmed_model",
            }
        ],
    )

    assert report.annotation_count == 1
    ann = next(item.annotation for item in batch.items if item.WhichOneof("item") == "annotation")
    assert ann.source == irpb.ANNOTATION_SOURCE_CONFIRMED_MODEL
