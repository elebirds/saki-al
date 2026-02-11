from enum import Enum


class ExecutorState(str, Enum):
    OFFLINE = "offline"
    CONNECTING = "connecting"
    IDLE = "idle"
    RESERVED = "reserved"
    RUNNING = "running"
    FINALIZING = "finalizing"
    ERROR_RECOVERY = "error_recovery"


class JobStatus(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL_FAILED = "partial_failed"
