from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class IRValidationIssue:
    code: str
    path: str
    message: str
    hint: str = ""
    value_preview: str = ""


class IRValidationError(Exception):
    """Structured validation error for ergonomic IR APIs."""

    def __init__(self, issues: list[IRValidationIssue]) -> None:
        if not issues:
            issues = [
                IRValidationIssue(
                    code="IR_VALIDATION_ERROR",
                    path="",
                    message="validation failed",
                )
            ]
        self.issues = list(issues)
        super().__init__(self.to_message())

    def to_dict(self) -> dict[str, Any]:
        return {
            "issues": [
                {
                    "code": item.code,
                    "path": item.path,
                    "message": item.message,
                    "hint": item.hint,
                    "value_preview": item.value_preview,
                }
                for item in self.issues
            ]
        }

    def to_message(self) -> str:
        parts: list[str] = []
        for item in self.issues:
            path = item.path or "<root>"
            part = f"[{item.code}] {item.message} (path={path})"
            if item.hint:
                part += f" hint={item.hint}"
            parts.append(part)
        return "; ".join(parts)

    def __str__(self) -> str:
        return self.to_message()


__all__ = [
    "IRValidationIssue",
    "IRValidationError",
]
