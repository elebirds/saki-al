from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from saki_executor.steps.state import TaskStatus

SUPPORTED_LOOP_MODES = {"active_learning", "simulation", "manual"}
SAMPLING_REQUIRED_TASK_TYPES = {"score", "custom"}


@dataclass(frozen=True)
class TaskExecutionRequest:
    task_id: str
    round_id: str
    task_type: str
    dispatch_kind: str
    plugin_id: str
    resolved_params: dict[str, Any]
    project_id: str
    input_commit_id: str
    query_strategy: str | None
    mode: str
    round_index: int
    attempt: int
    depends_on_task_ids: list[str]
    raw_payload: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "TaskExecutionRequest":
        task_type = str(payload.get("task_type") or "").strip().lower()
        if not task_type:
            raise ValueError("task_type is required")

        raw_round_index = payload.get("round_index")
        round_index = 0
        if raw_round_index is None or str(raw_round_index).strip() == "":
            if task_type != "predict":
                raise ValueError("round_index is required and must be a positive integer")
        else:
            try:
                round_index = int(raw_round_index)
            except Exception as exc:
                raise ValueError("round_index is required and must be a positive integer") from exc
        if task_type == "predict":
            if round_index < 0:
                raise ValueError("round_index must be >= 0 for predict task")
        elif round_index <= 0:
            raise ValueError("round_index is required and must be a positive integer")

        query_strategy = str(payload.get("query_strategy") or "").strip() or None

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
        if mode == "manual" and has_sampling and task_type != "predict":
            raise ValueError("manual mode does not allow sampling params")
        if mode in {"active_learning", "simulation"} and task_type in SAMPLING_REQUIRED_TASK_TYPES:
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

        task_id = str(payload.get("task_id") or "").strip()
        if not task_id:
            raise ValueError("task_id is required")

        return cls(
            task_id=task_id,
            round_id=str(payload.get("round_id") or ""),
            task_type=task_type,
            dispatch_kind=dispatch_kind,
            plugin_id=str(payload.get("plugin_id") or ""),
            resolved_params=resolved_params,
            project_id=str(payload.get("project_id") or ""),
            input_commit_id=str(payload.get("input_commit_id") or ""),
            query_strategy=query_strategy,
            mode=mode,
            round_index=round_index,
            attempt=max(1, int(payload.get("attempt") or 1)),
            depends_on_task_ids=[str(v) for v in (payload.get("depends_on_task_ids") or [])],
            raw_payload=dict(payload),
        )


@dataclass(frozen=True)
class FetchedPage:
    request_id: str
    reply_to: str
    task_id: str
    query_type: str
    items: list[dict[str, Any]]
    next_cursor: str | None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FetchedPage":
        return cls(
            request_id=str(payload.get("request_id") or ""),
            reply_to=str(payload.get("reply_to") or ""),
            task_id=str(payload.get("task_id") or ""),
            query_type=str(payload.get("query_type") or ""),
            items=list(payload.get("items") or []),
            next_cursor=str(payload["next_cursor"]) if payload.get("next_cursor") else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "reply_to": self.reply_to,
            "task_id": self.task_id,
            "query_type": self.query_type,
            "items": self.items,
            "next_cursor": self.next_cursor,
        }


@dataclass(frozen=True)
class ArtifactUploadTicket:
    request_id: str
    reply_to: str
    task_id: str
    upload_url: str
    storage_uri: str
    headers: dict[str, str]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ArtifactUploadTicket":
        return cls(
            request_id=str(payload.get("request_id") or ""),
            reply_to=str(payload.get("reply_to") or ""),
            task_id=str(payload.get("task_id") or ""),
            upload_url=str(payload.get("upload_url") or ""),
            storage_uri=str(payload.get("storage_uri") or ""),
            headers={str(k): str(v) for k, v in (payload.get("headers") or {}).items()},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "reply_to": self.reply_to,
            "task_id": self.task_id,
            "upload_url": self.upload_url,
            "storage_uri": self.storage_uri,
            "headers": self.headers,
        }


@dataclass(frozen=True)
class TaskFinalResult:
    task_id: str
    status: TaskStatus
    metrics: dict[str, Any]
    artifacts: dict[str, Any]
    candidates: list[dict[str, Any]]
    error_message: str = ""
