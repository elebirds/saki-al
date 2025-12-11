from enum import Enum

class JobStatus(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

class JobType(str, Enum):
    TRAIN_DETECTION = "train_detection"
    SCORE_UNLABELED = "score_unlabeled"
    EXPORT_MODEL = "export_model"

class EventType(str, Enum):
    LOG = "log"
    PROGRESS = "progress"
    METRIC = "metric"
    ARTIFACT = "artifact"
    STATUS = "status"

class ErrorCode(str, Enum):
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    UNAVAILABLE = "UNAVAILABLE"
    INTERNAL = "INTERNAL"
