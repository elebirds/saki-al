from saki_executor.plugins.builtin.yolo_det.plugin import YoloDetectionPlugin


def test_yolo_plugin_contract_fields():
    plugin = YoloDetectionPlugin()
    assert plugin.plugin_id == "yolo_det_v1"
    assert "train_detection" in plugin.supported_job_types
    assert "aug_iou_disagreement_v1" in plugin.supported_strategies


def test_yolo_plugin_validate_params():
    plugin = YoloDetectionPlugin()
    plugin.validate_params(
        {
            "epochs": 30,
            "batch": 16,
            "imgsz": 640,
            "topk": 200,
        }
    )
