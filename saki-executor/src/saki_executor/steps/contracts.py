from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from saki_executor.steps.state import StepStatus

SUPPORTED_LOOP_MODES = {"active_learning", "simulation", "manual"}
SAMPLING_REQUIRED_STEP_TYPES = {"train", "score", "custom"}


@dataclass(frozen=True)
class StepExecutionRequest:
    step_id: str
    round_id: str
    step_type: str
    dispatch_kind: str
    plugin_id: str
    resolved_params: dict[str, Any]
    project_id: str
    input_commit_id: str
    query_strategy: str | None
    mode: str
    round_index: int
    attempt: int
    depends_on_step_ids: list[str]
    raw_payload: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "StepExecutionRequest":
        raw_round_index = payload.get("round_index")
        try:
            round_index = int(raw_round_index)
        except Exception as exc:
            raise ValueError("round_index is required and must be a positive integer") from exc
        if round_index <= 0:
            raise ValueError("round_index is required and must be a positive integer")

        query_strategy = str(payload.get("query_strategy") or "").strip() or None

        step_type = str(payload.get("step_type") or "").strip().lower()
        if not step_type:
            raise ValueError("step_type is required")

        dispatch_kind = str(payload.get("dispatch_kind") or "").strip().lower()
        if not dispatch_kind:
            raise ValueError("dispatch_kind is required")
        if dispatch_kind not in {"dispatchable", "orchestrator"}:
            raise ValueError(f"unsupported dispatch_kind: {dispatch_kind or '<empty>'}")

        mode = str(payload.get("mode") or "").strip().lower()
        if mode not in SUPPORTED_LOOP_MODES:
            raise ValueError(f"unsupported mode: {mode or '<empty>'}")

        resolved_params = dict(payload.get("resolved_params") or {})
        sampling = resolved_params.get("sampling")
        sampling_cfg = sampling if isinstance(sampling, dict) else {}
        has_sampling = bool(sampling_cfg) or any(
            key in resolved_params for key in ("topk", "query_strategy", "sampling_topk")
        )
        if mode == "manual" and has_sampling:
            raise ValueError("manual mode does not allow sampling params")
        if mode in {"active_learning", "simulation"} and step_type in SAMPLING_REQUIRED_STEP_TYPES:
            strategy = str(sampling_cfg.get("strategy") or query_strategy or "").strip()
            fallback_topk = 200 if strategy else 0
            topk_raw = sampling_cfg.get("topk", resolved_params.get("topk", fallback_topk))
            try:
                topk = int(topk_raw)
            except Exception as exc:
                raise ValueError("sampling.topk is required for active_learning/simulation") from exc
            if not strategy:
                raise ValueError("sampling.strategy is required for active_learning/simulation")
            if topk <= 0:
                raise ValueError("sampling.topk must be > 0 for active_learning/simulation")

        step_id = str(payload.get("step_id") or "").strip()
        if not step_id:
            raise ValueError("step_id is required")

        return cls(
            step_id=step_id,
            round_id=str(payload.get("round_id") or ""),
            step_type=step_type,
            dispatch_kind=dispatch_kind,
            plugin_id=str(payload.get("plugin_id") or ""),
            resolved_params=resolved_params,
            project_id=str(payload.get("project_id") or ""),
            input_commit_id=str(payload.get("input_commit_id") or ""),
            query_strategy=query_strategy,
            mode=mode,
            round_index=round_index,
            attempt=max(1, int(payload.get("attempt") or 1)),
            depends_on_step_ids=[str(v) for v in (payload.get("depends_on_step_ids") or [])],
            raw_payload=dict(payload),
        )


@dataclass(frozen=True)
class FetchedPage:
    request_id: str
    reply_to: str
    step_id: str
    query_type: str
    items: list[dict[str, Any]]
    next_cursor: str | None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FetchedPage":
        return cls(
            request_id=str(payload.get("request_id") or ""),
            reply_to=str(payload.get("reply_to") or ""),
            step_id=str(payload.get("step_id") or ""),
            query_type=str(payload.get("query_type") or ""),
            items=list(payload.get("items") or []),
            next_cursor=str(payload["next_cursor"]) if payload.get("next_cursor") else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "reply_to": self.reply_to,
            "step_id": self.step_id,
            "query_type": self.query_type,
            "items": self.items,
            "next_cursor": self.next_cursor,
        }


@dataclass(frozen=True)
class ArtifactUploadTicket:
    request_id: str
    reply_to: str
    step_id: str
    upload_url: str
    storage_uri: str
    headers: dict[str, str]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ArtifactUploadTicket":
        return cls(
            request_id=str(payload.get("request_id") or ""),
            reply_to=str(payload.get("reply_to") or ""),
            step_id=str(payload.get("step_id") or ""),
            upload_url=str(payload.get("upload_url") or ""),
            storage_uri=str(payload.get("storage_uri") or ""),
            headers={str(k): str(v) for k, v in (payload.get("headers") or {}).items()},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "reply_to": self.reply_to,
            "step_id": self.step_id,
            "upload_url": self.upload_url,
            "storage_uri": self.storage_uri,
            "headers": self.headers,
        }


@dataclass(frozen=True)
class StepFinalResult:
    step_id: str
    status: StepStatus
    metrics: dict[str, Any]
    artifacts: dict[str, Any]
    candidates: list[dict[str, Any]]
    error_message: str = ""
