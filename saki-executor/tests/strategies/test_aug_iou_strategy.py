from saki_plugin_sdk.strategies.aug_iou import DetectionBox, score_aug_iou_disagreement


def _box(cls_id: int, conf: float, x1: float, y1: float, x2: float, y2: float) -> DetectionBox:
    return DetectionBox(cls_id=cls_id, conf=conf, xyxy=(x1, y1, x2, y2))


def test_aug_iou_disagreement_low_when_predictions_consistent():
    aug_preds = [
        [_box(0, 0.9, 10, 10, 50, 50)],
        [_box(0, 0.88, 10, 10, 50, 50)],
        [_box(0, 0.91, 10, 10, 50, 50)],
        [_box(0, 0.87, 10, 10, 50, 50)],
    ]
    score, reason = score_aug_iou_disagreement(aug_preds)
    assert 0.0 <= score <= 1.0
    assert reason["mean_iou"] > 0.95
    assert score < 0.2


def test_aug_iou_disagreement_high_when_predictions_diverge():
    aug_preds = [
        [_box(0, 0.95, 10, 10, 40, 40)],
        [_box(0, 0.7, 70, 70, 100, 100)],
        [_box(1, 0.8, 15, 15, 45, 45)],
        [],
    ]
    score, reason = score_aug_iou_disagreement(aug_preds)
    assert 0.0 <= score <= 1.0
    assert reason["mean_iou"] < 0.4
    assert reason["class_gap"] > 0.1
    assert score > 0.45
