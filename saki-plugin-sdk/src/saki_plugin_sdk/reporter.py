import json
import threading
import time
from pathlib import Path
from typing import Any


class TaskReporter:
    """Serializes step events to a local ``events.jsonl`` file."""

    def __init__(self, task_id: str, events_path: Path):
        self.task_id = task_id
        self.events_path = events_path
        self._lock = threading.Lock()
        self._seq = self._init_seq()

    def _init_seq(self) -> int:
        if not self.events_path.exists():
            return 0
        seq = 0
        with self.events_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    seq = max(seq, int(data.get("seq", 0)))
                except Exception:
                    continue
        return seq

    def _append(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._seq += 1
            event = {
                "task_id": self.task_id,
                "seq": self._seq,
                "ts": int(time.time()),
                "event_type": event_type,
                "payload": payload,
            }
            with self.events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
            return event

    def status(self, status: str, reason: str | None = None) -> dict[str, Any]:
        payload = {"status": status}
        if reason:
            payload["reason"] = reason
        return self._append("status", payload)

    def log(
        self,
        level: str,
        message: str,
        *,
        raw_message: str | None = None,
        message_key: str | None = None,
        message_args: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"level": level, "message": message}
        if raw_message is not None:
            payload["raw_message"] = raw_message
        if message_key:
            payload["message_key"] = message_key
        if message_args:
            payload["message_args"] = dict(message_args)
        if meta:
            payload["meta"] = dict(meta)
        return self._append("log", payload)

    def progress(self, epoch: int, step: int, total_steps: int, eta_sec: int | None = None) -> dict[str, Any]:
        payload = {
            "epoch": epoch,
            "step": step,
            "total_steps": total_steps,
        }
        if eta_sec is not None:
            payload["eta_sec"] = eta_sec
        return self._append("progress", payload)

    def metric(self, step: int, metrics: dict[str, float], epoch: int | None = None) -> dict[str, Any]:
        payload = {"step": step, "metrics": metrics}
        if epoch is not None:
            payload["epoch"] = epoch
        return self._append("metric", payload)

    def artifact(self, kind: str, name: str, uri: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {"kind": kind, "name": name, "uri": uri, "meta": meta or {}}
        return self._append("artifact", payload)
