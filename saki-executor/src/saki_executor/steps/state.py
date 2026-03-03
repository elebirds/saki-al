from enum import Enum


class ExecutorState(str, Enum):
    OFFLINE = "offline"
    CONNECTING = "connecting"
    IDLE = "idle"
    RESERVED = "reserved"
    RUNNING = "running"
    FINALIZING = "finalizing"
    ERROR_RECOVERY = "error_recovery"


class StepStatus(str, Enum):
    PENDING = "pending"
    DISPATCHING = "dispatching"
    SYNCING_ENV = "syncing_env"
    PROBING_RUNTIME = "probing_runtime"
    BINDING_DEVICE = "binding_device"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
