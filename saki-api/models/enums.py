from enum import Enum

class TaskType(str, Enum):
    """
    Enum for the type of computer vision task.
    """
    CLASSIFICATION = "classification"
    DETECTION = "detection"

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
