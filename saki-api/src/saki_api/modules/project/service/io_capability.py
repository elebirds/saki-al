from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from saki_ir import list_format_profiles


@dataclass(slots=True)
class IOCapabilityProfile:
    id: Literal["coco", "voc", "yolo", "yolo_obb", "dota"]
    family: str
    supports_import: bool
    supports_export: bool
    supported_annotation_types: list[str]
    yolo_label_options: list[str]
    available: bool
    reason: str | None


class IOCapabilityService:
    @staticmethod
    def build_profiles(*, enabled_annotation_types: list[str], mode: Literal["import", "export"]) -> list[IOCapabilityProfile]:
        normalized = {str(item).strip().lower() for item in enabled_annotation_types if str(item).strip()}
        profiles: list[IOCapabilityProfile] = []
        for profile in list_format_profiles():
            supports_mode = profile.supports_import if mode == "import" else profile.supports_export
            supported_types = set(profile.supported_annotation_types)
            if mode == "export":
                # Export must be compatible with the full project annotation policy, not only current snapshot overlap.
                annotation_supported = bool(normalized) and normalized.issubset(supported_types)
            else:
                # Import keeps existing behavior: allow profiles that overlap with enabled types.
                annotation_supported = bool(normalized) and any(item in normalized for item in supported_types)
            available = supports_mode and annotation_supported
            reason = None
            if not supports_mode:
                reason = f"{mode}_not_supported"
            elif not available:
                reason = "annotation_type_not_supported"
            profiles.append(
                IOCapabilityProfile(
                    id=profile.id,
                    family=profile.family,
                    supports_import=profile.supports_import,
                    supports_export=profile.supports_export,
                    supported_annotation_types=list(profile.supported_annotation_types),
                    yolo_label_options=list(profile.yolo_label_options),
                    available=available,
                    reason=reason,
                )
            )
        return profiles
