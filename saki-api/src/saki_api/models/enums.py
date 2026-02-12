from enum import Enum


class StorageType(str, Enum):
    LOCAL = "local"
    S3 = "s3"


class AuthorType(str, Enum):
    USER = "user"
    MODEL = "model"
    SYSTEM = "system"


class TaskType(str, Enum):
    """
    Enum for the type of machine learning task.
    Used for active learning and CV model training.
    """
    CLASSIFICATION = "classification"
    DETECTION = "detection"
    SEGMENTATION = "segmentation"


class AnnotationType(str, Enum):
    """
    Enum for the geometric type of an annotation.
    Determines how the annotation data should be interpreted.
    """
    # Bounding box - axis-aligned rectangle
    RECT = "rect"
    # Oriented bounding box - rotated rectangle
    OBB = "obb"
    # Polygon - arbitrary closed shape
    POLYGON = "polygon"
    # Polyline - open path
    POLYLINE = "polyline"
    # Point - single coordinate
    POINT = "point"
    # Keypoints - multiple named points
    KEYPOINTS = "keypoints"


class AnnotationSource(str, Enum):
    """
    Enum for the source/origin of an annotation.
    Used to distinguish human annotations from auto-generated ones.
    """
    # Manual annotation by human annotator
    MANUAL = "manual"
    # Model prediction (from active learning or inference)
    MODEL = "model"
    # System-generated (e.g., FEDO dual-view mapping)
    SYSTEM = "system"
    # Imported from external source
    IMPORTED = "imported"


class DatasetType(str, Enum):
    """
    Enum for the type of dataset.
    Determines which annotation UI to use.
    """
    # Classic - standard image annotation
    CLASSIC = "classic"
    # FEDO - dual-view for satellite electron energy data
    FEDO = "fedo"


class SampleStatus(str, Enum):
    """
    Enum for the status of a data sample.
    """
    UNLABELED = "unlabeled"
    LABELED = "labeled"
    SKIPPED = "skipped"


class CommitSampleReviewState(str, Enum):
    """
    Enum for sample review state at a specific commit.
    """
    LABELED = "labeled"
    EMPTY_CONFIRMED = "empty_confirmed"


class ProjectStatus(str, Enum):
    """
    Enum for the status of a project.
    """
    ACTIVE = "active"
    ARCHIVED = "archived"


class ModelStatus(str, Enum):
    """
    Enum for the status of a model version training process.
    """
    TRAINING = "training"
    READY = "ready"
    FAILED = "failed"


class TrainingJobStatus(str, Enum):
    """
    Enum for the status of a training job.
    """
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL_FAILED = "partial_failed"
    CANCELLED = "cancelled"


class ALLoopStatus(str, Enum):
    """
    Enum for active-learning loop lifecycle.
    """
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"


class ALLoopMode(str, Enum):
    """
    Enum for active-learning execution mode.
    """
    ACTIVE_LEARNING = "active_learning"
    SIMULATION = "simulation"
    MANUAL = "manual"


class LoopPhase(str, Enum):
    """
    Enum for loop phase state machine.
    """
    AL_BOOTSTRAP = "al_bootstrap"
    AL_TRAIN = "al_train"
    AL_SCORE = "al_score"
    AL_WAIT_ANNOTATION = "al_wait_annotation"
    AL_MERGE = "al_merge"
    AL_EVAL = "al_eval"

    SIM_BOOTSTRAP = "sim_bootstrap"
    SIM_TRAIN = "sim_train"
    SIM_SCORE = "sim_score"
    SIM_AUTO_LABEL = "sim_auto_label"
    SIM_EVAL = "sim_eval"

    MANUAL_IDLE = "manual_idle"
    MANUAL_TASK_RUNNING = "manual_task_running"
    MANUAL_WAIT_CONFIRM = "manual_wait_confirm"
    MANUAL_FINALIZE = "manual_finalize"


class JobStatusV2(str, Enum):
    """
    Enum for aggregated Job status.
    """
    JOB_PENDING = "job_pending"
    JOB_RUNNING = "job_running"
    JOB_PARTIAL_FAILED = "job_partial_failed"
    JOB_FAILED = "job_failed"
    JOB_SUCCEEDED = "job_succeeded"
    JOB_CANCELLED = "job_cancelled"


class JobTaskType(str, Enum):
    """
    Enum for runtime task type in L3 runtime context.
    """
    TRAIN = "train"
    SCORE = "score"
    SELECT = "select"
    AUTO_LABEL = "auto_label"
    WAIT_ANNOTATION = "wait_annotation"
    MERGE = "merge"
    EVAL = "eval"
    UPLOAD_ARTIFACT = "upload_artifact"
    MANUAL_REVIEW = "manual_review"


class JobTaskStatus(str, Enum):
    """
    Enum for runtime task execution status.
    """
    PENDING = "pending"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class LoopRoundStatus(str, Enum):
    """
    Enum for per-round state in an active-learning loop.
    """
    TRAINING = "training"
    ANNOTATION = "annotation"
    COMPLETED = "completed"
    COMPLETED_NO_CANDIDATES = "completed_no_candidates"
    FAILED = "failed"
