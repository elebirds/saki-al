from __future__ import annotations

from saki_ir import get_format_profile, list_format_profiles


def test_format_profiles_include_predictions_json():
    ids = [profile.id for profile in list_format_profiles()]

    assert "predictions_json" in ids


def test_predictions_json_profile_contract():
    profile = get_format_profile("predictions_json")

    assert profile.id == "predictions_json"
    assert profile.family == "prediction_json"
    assert profile.supports_import is False
    assert profile.supports_export is True
    assert profile.supported_annotation_types == ("rect", "obb")
    assert profile.yolo_label_options == ()
