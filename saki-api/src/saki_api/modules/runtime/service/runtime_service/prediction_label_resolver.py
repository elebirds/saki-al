"""Prediction label resolution against frozen prediction_set binding."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from saki_api.modules.runtime.domain.prediction_set_binding import PredictionSetBinding


def _safe_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except Exception:
        return None


def _first_non_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _parse_class_index(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _normalize_class_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    return " ".join(text.split())


@dataclass(frozen=True, slots=True)
class PredictionResolveError(ValueError):
    code: str
    message: str
    sample_id: str = ""
    class_index: int | None = None
    class_name: str = ""

    def to_error_message(self) -> str:
        base = f"[{self.code}] {self.message} (phase=prediction_resolve)"
        details: list[str] = []
        if self.sample_id:
            details.append(f"sample_id={self.sample_id}")
        if self.class_index is not None:
            details.append(f"class_index={self.class_index}")
        if self.class_name:
            details.append(f"class_name={self.class_name}")
        if not details:
            return base
        return f"{base} {' '.join(details)}"


@dataclass(frozen=True, slots=True)
class PredictionLabelDecision:
    label_id: uuid.UUID
    source: str
    class_index: int | None
    class_name: str


class PredictionLabelResolver:
    def __init__(
        self,
        *,
        by_index: list[uuid.UUID | None],
        by_name: dict[str, uuid.UUID],
        schema_hash: str,
        model_id: uuid.UUID,
    ) -> None:
        self._by_index = list(by_index)
        self._by_name = dict(by_name)
        self._schema_hash = str(schema_hash or "")
        self._model_id = model_id
        self._known_labels = {item for item in self._by_index if item is not None} | set(self._by_name.values())

    @property
    def schema_hash(self) -> str:
        return self._schema_hash

    @property
    def model_id(self) -> uuid.UUID:
        return self._model_id

    @classmethod
    def from_binding(cls, binding: PredictionSetBinding) -> "PredictionLabelResolver":
        by_index_raw = list(binding.by_index_json or [])
        by_index: list[uuid.UUID | None] = []
        for value in by_index_raw:
            by_index.append(_safe_uuid(value))

        by_name_raw = dict(binding.by_name_json or {})
        by_name: dict[str, uuid.UUID] = {}
        for key, value in by_name_raw.items():
            key_norm = _normalize_class_name(key)
            value_uuid = _safe_uuid(value)
            if not key_norm or value_uuid is None:
                continue
            by_name[key_norm] = value_uuid

        return cls(
            by_index=by_index,
            by_name=by_name,
            schema_hash=str(binding.schema_hash or ""),
            model_id=binding.model_id,
        )

    def resolve(
        self,
        *,
        snapshot: dict[str, Any],
        prediction: dict[str, Any],
        fallback_label_id: uuid.UUID | None = None,
        sample_id: str = "",
    ) -> PredictionLabelDecision:
        explicit_label_id = _safe_uuid(
            _first_non_none(
                prediction.get("label_id"),
                snapshot.get("label_id"),
            )
        )
        class_name_raw = _first_non_none(
            prediction.get("class_name"),
            snapshot.get("class_name"),
        )
        class_name = str(class_name_raw or "").strip()
        class_name_norm = _normalize_class_name(class_name)
        class_index = _parse_class_index(
            _first_non_none(
                prediction.get("class_index"),
                snapshot.get("class_index"),
            )
        )

        by_name_label = self._by_name.get(class_name_norm) if class_name_norm else None
        by_index_label = None
        if class_index is not None and 0 <= class_index < len(self._by_index):
            by_index_label = self._by_index[class_index]

        if (
            explicit_label_id is None
            and fallback_label_id is not None
            and not class_name_norm
            and class_index is None
        ):
            explicit_label_id = fallback_label_id

        candidates = {
            "explicit": explicit_label_id,
            "class_name": by_name_label,
            "class_index": by_index_label,
        }
        unique_ids = {value for value in candidates.values() if value is not None}

        if explicit_label_id is not None and explicit_label_id not in self._known_labels:
            raise PredictionResolveError(
                code="PREDICTION_BINDING_MISMATCH",
                message="explicit label_id is not part of prediction_set binding",
                sample_id=sample_id,
                class_index=class_index,
                class_name=class_name,
            )

        if len(unique_ids) > 1:
            raise PredictionResolveError(
                code="PREDICTION_LABEL_CONFLICT",
                message=(
                    f"prediction label sources conflict: explicit={candidates['explicit']} "
                    f"class_name={candidates['class_name']} class_index={candidates['class_index']}"
                ),
                sample_id=sample_id,
                class_index=class_index,
                class_name=class_name,
            )

        label_id = explicit_label_id or by_name_label or by_index_label
        if label_id is None:
            raise PredictionResolveError(
                code="PREDICTION_LABEL_UNRESOLVED",
                message="cannot resolve label from prediction payload",
                sample_id=sample_id,
                class_index=class_index,
                class_name=class_name,
            )

        if explicit_label_id is not None:
            source = "explicit"
        elif by_name_label is not None:
            source = "class_name"
        else:
            source = "class_index"

        return PredictionLabelDecision(
            label_id=label_id,
            source=source,
            class_index=class_index,
            class_name=class_name,
        )
