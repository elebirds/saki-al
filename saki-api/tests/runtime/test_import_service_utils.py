from pathlib import Path

import pytest

from saki_api.core.exceptions import BadRequestAppException
from saki_api.modules.importing.schema import ImportIssue, NameCollisionPolicy, PathFlattenMode
from saki_api.modules.importing.service.import_service import ImportService, PreparedAnnotation


def test_deterministic_uuid_mapping_is_stable() -> None:
    first = ImportService._deterministic_uuid("lineage", "p1", "d1", "a/b.jpg", "ann-1")
    second = ImportService._deterministic_uuid("lineage", "p1", "d1", "a/b.jpg", "ann-1")
    third = ImportService._deterministic_uuid("lineage", "p1", "d1", "a/b.jpg", "ann-2")

    assert first == second
    assert first != third


def test_normalize_zip_entry_name_rejects_path_traversal() -> None:
    with pytest.raises(BadRequestAppException):
        ImportService._normalize_zip_entry_name("../evil.jpg")

    with pytest.raises(BadRequestAppException):
        ImportService._normalize_zip_entry_name("/absolute/path.jpg")

    with pytest.raises(BadRequestAppException):
        ImportService._normalize_zip_entry_name("C:/windows/path.jpg")


def test_resolve_name_uses_exact_then_unique_basename() -> None:
    exact, basename = ImportService._build_name_lookup({"a/x.jpg", "b/y.jpg", "c/z.jpg"})

    resolved_exact, via_basename_exact = ImportService._resolve_name("a/x.jpg", exact, basename)
    resolved_base, via_basename = ImportService._resolve_name("z.jpg", exact, basename)
    resolved_none, via_basename_none = ImportService._resolve_name("missing.jpg", exact, basename)

    assert resolved_exact == "a/x.jpg"
    assert via_basename_exact is False

    assert resolved_base == "c/z.jpg"
    assert via_basename is True

    assert resolved_none is None
    assert via_basename_none is False


def test_count_unsupported_annotation_types() -> None:
    prepared = [
        PreparedAnnotation(
            sample_key="a.jpg",
            label_name="car",
            ann_type="rect",
            geometry={"rect": {"x": 1, "y": 1, "width": 1, "height": 1}},
            confidence=1.0,
            attrs={},
            lineage_seed="1",
        ),
        PreparedAnnotation(
            sample_key="b.jpg",
            label_name="car",
            ann_type="obb",
            geometry={"obb": {"cx": 1, "cy": 1, "width": 1, "height": 1, "angle_deg_ccw": 0}},
            confidence=1.0,
            attrs={},
            lineage_seed="2",
        ),
        PreparedAnnotation(
            sample_key="c.jpg",
            label_name="car",
            ann_type="rect",
            geometry={"rect": {"x": 2, "y": 2, "width": 2, "height": 2}},
            confidence=1.0,
            attrs={},
            lineage_seed="3",
        ),
    ]
    unsupported = ImportService._count_unsupported_annotation_types(
        prepared_annotations=prepared,
        enabled_type_values={"obb"},
    )
    assert unsupported == {"rect": 2}


def test_append_unsupported_type_issues() -> None:
    errors: list[ImportIssue] = []
    ImportService._append_unsupported_type_issues(
        errors=errors,
        unsupported_type_counts={"rect": 3},
        enabled_type_values={"obb"},
    )
    assert len(errors) == 1
    assert errors[0].code == "ANNOTATION_TYPE_NOT_ENABLED"
    assert "rect" in errors[0].message
    assert errors[0].detail == {
        "annotation_type": "rect",
        "count": 3,
        "enabled_types": ["obb"],
    }


def test_manifest_has_error_code_matches_case_insensitive() -> None:
    manifest = {
        "errors": [
            {"code": "annotation_type_not_enabled", "message": "blocked"},
            {"code": "SAMPLE_NOT_FOUND", "message": "missing"},
        ]
    }
    assert ImportService._manifest_has_error_code(manifest, "ANNOTATION_TYPE_NOT_ENABLED") is True
    assert ImportService._manifest_has_error_code(manifest, "sample_not_found") is True


def test_manifest_has_error_code_returns_false_when_missing() -> None:
    manifest = {"errors": [{"code": "SOMETHING_ELSE"}]}
    assert ImportService._manifest_has_error_code(manifest, "ANNOTATION_TYPE_NOT_ENABLED") is False


def test_build_image_entries_basename_abort_collision() -> None:
    service = object.__new__(ImportService)
    warnings: list[ImportIssue] = []
    errors: list[ImportIssue] = []

    entries = service._build_image_entries(
        image_paths=["a/b/c/file.jpg", "x/y/file.jpg"],
        path_flatten_mode=PathFlattenMode.BASENAME,
        name_collision_policy=NameCollisionPolicy.ABORT,
        warnings=warnings,
        errors=errors,
    )

    assert len(entries) == 1
    assert entries[0].resolved_sample_name == "file.jpg"
    assert any(item.code == "IMAGE_NAME_COLLISION" for item in errors)


def test_build_image_entries_basename_auto_rename_collision() -> None:
    service = object.__new__(ImportService)
    warnings: list[ImportIssue] = []
    errors: list[ImportIssue] = []

    entries = service._build_image_entries(
        image_paths=["a/b/c/file.jpg", "x/y/file.jpg"],
        path_flatten_mode=PathFlattenMode.BASENAME,
        name_collision_policy=NameCollisionPolicy.AUTO_RENAME,
        warnings=warnings,
        errors=errors,
    )

    assert len(entries) == 2
    assert entries[0].resolved_sample_name == "file.jpg"
    assert entries[1].resolved_sample_name != "file.jpg"
    assert "__" in entries[1].resolved_sample_name
    assert entries[1].collision_action == "renamed"
    assert any(item.code == "IMAGE_NAME_AUTO_RENAMED" for item in warnings)
    assert not errors


def test_build_image_entries_basename_overwrite_collision() -> None:
    service = object.__new__(ImportService)
    warnings: list[ImportIssue] = []
    errors: list[ImportIssue] = []

    entries = service._build_image_entries(
        image_paths=["a/b/c/file.jpg", "x/y/file.jpg"],
        path_flatten_mode=PathFlattenMode.BASENAME,
        name_collision_policy=NameCollisionPolicy.OVERWRITE,
        warnings=warnings,
        errors=errors,
    )

    assert len(entries) == 1
    assert entries[0].resolved_sample_name == "file.jpg"
    assert entries[0].zip_entry_path == "x/y/file.jpg"
    assert entries[0].collision_action == "overwritten"
    assert any(item.code == "IMAGE_NAME_OVERWRITTEN" for item in warnings)
    assert not errors


def test_manifest_image_entries_requires_image_entries_field() -> None:
    manifest = {
        "image_paths": ["a/b/c/file.jpg"],
    }
    entries = ImportService._manifest_image_entries(manifest)
    assert entries == []


def test_build_voc_import_split_merges_split_keys_and_annotation_xmls(tmp_path: Path) -> None:
    voc_root = tmp_path / "VOC2007"
    ann_dir = voc_root / "Annotations"
    set_dir = voc_root / "ImageSets" / "Main"
    ann_dir.mkdir(parents=True, exist_ok=True)
    set_dir.mkdir(parents=True, exist_ok=True)

    (ann_dir / "009961.xml").write_text("<annotation/>", encoding="utf-8")
    (ann_dir / "009962.xml").write_text("<annotation/>", encoding="utf-8")
    (ann_dir / "009963.xml").write_text("<annotation/>", encoding="utf-8")

    # train/test overlap and use VOC style "key flag" line.
    (set_dir / "train.txt").write_text("009961\n009962\n", encoding="utf-8")
    (set_dir / "test.txt").write_text("009962 1\n010000 -1\n", encoding="utf-8")

    split = ImportService._build_voc_import_split(voc_root)
    assert split == "__saki_import_all__"

    generated = set_dir / "__saki_import_all__.txt"
    lines = [line.strip() for line in generated.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines == sorted({"009961", "009962", "009963", "010000"})


def test_build_voc_import_split_falls_back_to_annotations_when_split_missing(tmp_path: Path) -> None:
    voc_root = tmp_path / "VOC"
    ann_dir = voc_root / "Annotations"
    set_dir = voc_root / "ImageSets" / "Main"
    ann_dir.mkdir(parents=True, exist_ok=True)
    set_dir.mkdir(parents=True, exist_ok=True)

    (ann_dir / "a.xml").write_text("<annotation/>", encoding="utf-8")
    (ann_dir / "b.xml").write_text("<annotation/>", encoding="utf-8")

    split = ImportService._build_voc_import_split(voc_root)
    assert split == "__saki_import_all__"

    generated = set_dir / "__saki_import_all__.txt"
    lines = [line.strip() for line in generated.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines == ["a", "b"]
