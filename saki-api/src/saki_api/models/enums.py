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


class AnnotationSystemType(str, Enum):
    """
    Enum for the type of annotation system/interface.
    Determines which annotation UI to use.
    """
    # Classic annotation system - standard image annotation
    CLASSIC = "classic"
    # FEDO annotation system - dual-view for satellite electron energy data
    FEDO = "fedo"


class SampleStatus(str, Enum):
    """
    Enum for the status of a data sample.
    """
    UNLABELED = "unlabeled"
    LABELED = "labeled"
    SKIPPED = "skipped"


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
    CANCELLED = "cancelled"

