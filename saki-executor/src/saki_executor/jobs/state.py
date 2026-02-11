from enum import Enum


class ExecutorState(str, Enum):
    OFFLINE = "offline"
    CONNECTING = "connecting"
    IDLE = "idle"
    RESERVED = "reserved"
    RUNNING = "running"
    FINALIZING = "finalizing"
    ERROR_RECOVERY = "error_recovery"


class TaskStatus(str, Enum):
    PENDING = "pending"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
