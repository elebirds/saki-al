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
    # Model prediction confirmed by user
    CONFIRMED_MODEL = "confirmed_model"


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


class LoopLifecycle(str, Enum):
    """
    Enum for loop lifecycle.
    """
    DRAFT = "draft"
    RUNNING = "running"
    PAUSING = "pausing"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"


class LoopMode(str, Enum):
    """
    Enum for loop execution mode.
    """
    ACTIVE_LEARNING = "active_learning"
    SIMULATION = "simulation"
    MANUAL = "manual"


class LoopGate(str, Enum):
    """
    Enum for user-facing loop interaction gate.
    """
    NEED_SNAPSHOT = "need_snapshot"
    NEED_LABELS = "need_labels"
    CAN_START = "can_start"
    RUNNING = "running"
    PAUSING = "pausing"
    PAUSED = "paused"
    STOPPING = "stopping"
    NEED_ROUND_LABELS = "need_round_labels"
    CAN_CONFIRM = "can_confirm"
    CAN_NEXT_ROUND = "can_next_round"
    CAN_RETRY = "can_retry"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class LoopActionKey(str, Enum):
    """Enum for loop-level action dispatch."""

    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    CONFIRM = "confirm"
    START_NEXT_ROUND = "start_next_round"
    RETRY_ROUND = "retry_round"
    SNAPSHOT_INIT = "snapshot_init"
    SNAPSHOT_UPDATE = "snapshot_update"
    SELECTION_ADJUST = "selection_adjust"
    READ = "read"
    OBSERVE = "observe"
    ANNOTATE = "annotate"


class LoopPhase(str, Enum):
    """
    Enum for loop phase state machine.
    """
    AL_BOOTSTRAP = "al_bootstrap"
    AL_TRAIN = "al_train"
    AL_EVAL = "al_eval"
    AL_SCORE = "al_score"
    AL_SELECT = "al_select"
    AL_WAIT_USER = "al_wait_user"
    AL_FINALIZE = "al_finalize"

    SIM_BOOTSTRAP = "sim_bootstrap"
    SIM_TRAIN = "sim_train"
    SIM_EVAL = "sim_eval"
    SIM_SCORE = "sim_score"
    SIM_SELECT = "sim_select"
    SIM_WAIT_USER = "sim_wait_user"
    SIM_FINALIZE = "sim_finalize"

    MANUAL_BOOTSTRAP = "manual_bootstrap"
    MANUAL_TRAIN = "manual_train"
    MANUAL_EVAL = "manual_eval"
    MANUAL_FINALIZE = "manual_finalize"


class LoopPauseReason(str, Enum):
    """
    Enum for resumable loop pause reason.
    """
    USER = "user"
    MAINTENANCE = "maintenance"


class RuntimeMaintenanceMode(str, Enum):
    """
    Enum for runtime maintenance mode.
    """
    NORMAL = "normal"
    DRAIN = "drain"
    PAUSE_NOW = "pause_now"


class SnapshotUpdateMode(str, Enum):
    """
    Enum for snapshot version update mode.
    """
    INIT = "init"
    APPEND_ALL_TO_POOL = "append_all_to_pool"
    APPEND_SPLIT = "append_split"


class SnapshotValPolicy(str, Enum):
    """
    Enum for validation policy in AL snapshot.
    """
    ANCHOR_ONLY = "anchor_only"
    EXPAND_WITH_BATCH_VAL = "expand_with_batch_val"


class SnapshotPartition(str, Enum):
    """
    Enum for snapshot sample partition.
    """
    TRAIN_SEED = "train_seed"
    TRAIN_POOL = "train_pool"
    VAL_ANCHOR = "val_anchor"
    VAL_BATCH = "val_batch"
    TEST_ANCHOR = "test_anchor"
    TEST_BATCH = "test_batch"


class VisibilitySource(str, Enum):
    """
    Enum for AL loop visibility source.
    """
    SNAPSHOT_INIT = "snapshot_init"
    SEED_INIT = "seed_init"
    ROUND_REVEAL = "round_reveal"
    FORCE_REVEAL = "force_reveal"


class RoundSelectionOverrideOp(str, Enum):
    """Enum for manual round candidate override operation."""

    INCLUDE = "include"
    EXCLUDE = "exclude"


class RoundStatus(str, Enum):
    """
    Enum for aggregated Round status.
    """
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class StepType(str, Enum):
    """
    Enum for runtime step type in L3 runtime context.
    """
    TRAIN = "train"
    EVAL = "eval"
    SCORE = "score"
    SELECT = "select"
    CUSTOM = "custom"


class StepDispatchKind(str, Enum):
    """
    Enum for step execution ownership.
    """
    DISPATCHABLE = "dispatchable"
    ORCHESTRATOR = "orchestrator"


class StepStatus(str, Enum):
    """
    Enum for runtime step execution status.
    """
    PENDING = "pending"
    READY = "ready"
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


class RuntimeTaskKind(str, Enum):
    """
    Enum for runtime execution task domain.
    """

    STEP = "step"
    PREDICTION = "prediction"


class RuntimeTaskType(str, Enum):
    """
    Enum for runtime execution task type.
    """

    TRAIN = "train"
    EVAL = "eval"
    SCORE = "score"
    SELECT = "select"
    PREDICT = "predict"
    CUSTOM = "custom"


class RuntimeTaskStatus(str, Enum):
    """
    Enum for runtime task execution status.
    """

    PENDING = "pending"
    READY = "ready"
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


class LoopRoundStatus(str, Enum):
    """
    Enum for per-round state in an active-learning loop.
    """
    TRAINING = "training"
    ANNOTATION = "annotation"
    COMPLETED = "completed"
    COMPLETED_NO_CANDIDATES = "completed_no_candidates"
    FAILED = "failed"
