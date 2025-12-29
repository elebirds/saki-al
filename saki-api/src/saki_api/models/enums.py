from enum import Enum


class TaskType(str, Enum):
    """
    Enum for the type of machine learning task.
    Used for active learning and CV model training.
    """
    CLASSIFICATION = "classification"
    DETECTION = "detection"
    SEGMENTATION = "segmentation"


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
