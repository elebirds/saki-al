from typing import Dict, Set

from saki_runtime.schemas.enums import JobStatus


class JobStateMachine:
    """
    Strict state machine for JobStatus.
    Transitions:
    created -> queued
    queued -> running
    running -> stopping
    running -> succeeded
    running -> failed
    stopping -> stopped
    """

    _TRANSITIONS: Dict[JobStatus, Set[JobStatus]] = {
        JobStatus.CREATED: {JobStatus.QUEUED, JobStatus.RUNNING}, # Allow direct running for MVP simplicity if no queue
        JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.STOPPED}, # Can be cancelled while queued
        JobStatus.RUNNING: {JobStatus.STOPPING, JobStatus.SUCCEEDED, JobStatus.FAILED},
        JobStatus.STOPPING: {JobStatus.STOPPED, JobStatus.FAILED}, # Failed if stopping fails? Or just stopped.
        JobStatus.STOPPED: set(),
        JobStatus.SUCCEEDED: set(),
        JobStatus.FAILED: set(),
    }

    @classmethod
    def can_transition(cls, current: JobStatus, target: JobStatus) -> bool:
        if current == target:
            return True  # Idempotency
        return target in cls._TRANSITIONS.get(current, set())

    @classmethod
    def validate_transition(cls, current: JobStatus, target: JobStatus) -> None:
        if not cls.can_transition(current, target):
            raise ValueError(f"Invalid state transition: {current} -> {target}")

    @classmethod
    def is_terminal(cls, status: JobStatus) -> bool:
        return status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.STOPPED}

    @classmethod
    def is_active(cls, status: JobStatus) -> bool:
        return status in {JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.STOPPING}
