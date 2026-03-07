from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

FormatProfileId = Literal["coco", "voc", "yolo", "yolo_obb", "dota"]
AnnotationShape = Literal["rect", "obb"]
YoloLabelOption = Literal["det", "obb_rbox", "obb_poly8"]


@dataclass(frozen=True, slots=True)
class FormatProfile:
    id: FormatProfileId
    family: str
    supports_import: bool
    supports_export: bool
    supported_annotation_types: tuple[AnnotationShape, ...]
    yolo_label_options: tuple[YoloLabelOption, ...]


_FORMAT_PROFILES: tuple[FormatProfile, ...] = (
    FormatProfile(
        id="coco",
        family="coco",
        supports_import=True,
        supports_export=True,
        supported_annotation_types=("rect",),
        yolo_label_options=(),
    ),
    FormatProfile(
        id="voc",
        family="voc",
        supports_import=True,
        supports_export=True,
        supported_annotation_types=("rect",),
        yolo_label_options=(),
    ),
    FormatProfile(
        id="yolo",
        family="yolo",
        supports_import=True,
        supports_export=True,
        supported_annotation_types=("rect",),
        yolo_label_options=("det",),
    ),
    FormatProfile(
        id="yolo_obb",
        family="yolo",
        supports_import=True,
        supports_export=True,
        supported_annotation_types=("rect", "obb"),
        yolo_label_options=("obb_rbox", "obb_poly8"),
    ),
    FormatProfile(
        id="dota",
        family="dota",
        supports_import=True,
        supports_export=True,
        supported_annotation_types=("rect", "obb"),
        yolo_label_options=(),
    ),
)

_PROFILE_BY_ID: dict[FormatProfileId, FormatProfile] = {profile.id: profile for profile in _FORMAT_PROFILES}


def list_format_profiles() -> tuple[FormatProfile, ...]:
    return _FORMAT_PROFILES


def get_format_profile(profile_id: FormatProfileId) -> FormatProfile:
    return _PROFILE_BY_ID[profile_id]


def filter_profiles_by_annotation_types(enabled_types: Iterable[str]) -> tuple[FormatProfile, ...]:
    normalized = {str(item).strip().lower() for item in enabled_types if str(item).strip()}
    if not normalized:
        return ()
    return tuple(
        profile
        for profile in _FORMAT_PROFILES
        if any(annotation_type in normalized for annotation_type in profile.supported_annotation_types)
    )
