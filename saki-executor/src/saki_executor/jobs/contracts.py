from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from saki_executor.jobs.state import JobStatus

SUPPORTED_JOB_MODES = {"active_learning", "simulation"}


@dataclass(frozen=True)
class JobExecutionRequest:
    job_id: str
    plugin_id: str
    params: dict[str, Any]
    project_id: str
    source_commit_id: str
    query_strategy: str
    mode: str
    round_index: int
    raw_payload: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> JobExecutionRequest:
        raw_round_index = payload.get("round_index")
        try:
            round_index = int(raw_round_index)
        except Exception as exc:
            raise ValueError("round_index is required and must be a positive integer") from exc
        if round_index <= 0:
            raise ValueError("round_index is required and must be a positive integer")

        query_strategy = str(payload.get("query_strategy") or "").strip()
        if not query_strategy:
            raise ValueError("query_strategy is required")

        mode = str(payload.get("mode") or "").strip().lower()
        if mode not in SUPPORTED_JOB_MODES:
            raise ValueError(f"unsupported mode: {mode or '<empty>'}")

        return cls(
            job_id=str(payload.get("job_id") or ""),
            plugin_id=str(payload.get("plugin_id") or ""),
            params=dict(payload.get("params") or {}),
            project_id=str(payload.get("project_id") or ""),
            source_commit_id=str(payload.get("source_commit_id") or ""),
            query_strategy=query_strategy,
            mode=mode,
            round_index=round_index,
            raw_payload=dict(payload),
        )


@dataclass(frozen=True)
class FetchedPage:
    request_id: str
    reply_to: str
    job_id: str
    query_type: str
    items: list[dict[str, Any]]
    next_cursor: str | None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> FetchedPage:
        return cls(
            request_id=str(payload.get("request_id") or ""),
            reply_to=str(payload.get("reply_to") or ""),
            job_id=str(payload.get("job_id") or ""),
            query_type=str(payload.get("query_type") or ""),
            items=list(payload.get("items") or []),
            next_cursor=str(payload["next_cursor"]) if payload.get("next_cursor") else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "reply_to": self.reply_to,
            "job_id": self.job_id,
            "query_type": self.query_type,
            "items": self.items,
            "next_cursor": self.next_cursor,
        }


@dataclass(frozen=True)
class ArtifactUploadTicket:
    request_id: str
    reply_to: str
    job_id: str
    upload_url: str
    storage_uri: str
    headers: dict[str, str]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ArtifactUploadTicket:
        return cls(
            request_id=str(payload.get("request_id") or ""),
            reply_to=str(payload.get("reply_to") or ""),
            job_id=str(payload.get("job_id") or ""),
            upload_url=str(payload.get("upload_url") or ""),
            storage_uri=str(payload.get("storage_uri") or ""),
            headers={str(k): str(v) for k, v in (payload.get("headers") or {}).items()},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "reply_to": self.reply_to,
            "job_id": self.job_id,
            "upload_url": self.upload_url,
            "storage_uri": self.storage_uri,
            "headers": self.headers,
        }


@dataclass(frozen=True)
class JobFinalResult:
    job_id: str
    status: JobStatus
    metrics: dict[str, Any]
    artifacts: dict[str, Any]
    candidates: list[dict[str, Any]]
    error_message: str = ""
