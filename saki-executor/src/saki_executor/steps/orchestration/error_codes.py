from __future__ import annotations

from enum import Enum


class StepStage(str, Enum):
    REQUEST_VALIDATION = "request_validation"
    PLUGIN_RESOLUTION = "plugin_resolution"
    SYNCING_ENV = "syncing_env"
    PROBING_RUNTIME = "probing_runtime"
    BINDING_DEVICE = "binding_device"
    POST_BIND_VALIDATION = "post_bind_validation"
    PREPARE_DATA = "prepare_data"
    EXECUTE = "execute"
    FINALIZE = "finalize"


class StepErrorCode(str, Enum):
    REQUEST_INVALID = "REQUEST_INVALID"
    PLUGIN_NOT_FOUND = "PLUGIN_NOT_FOUND"
    PLUGIN_UNSUPPORTED_STEP_TYPE = "PLUGIN_UNSUPPORTED_STEP_TYPE"
    CONFIG_RESOLVE_FAILED = "CONFIG_RESOLVE_FAILED"
    PARAM_VALIDATE_FAILED = "PARAM_VALIDATE_FAILED"
    PROFILE_UNSATISFIED = "PROFILE_UNSATISFIED"
    ENV_SYNC_FAILED = "ENV_SYNC_FAILED"
    RUNTIME_PROBE_FAILED = "RUNTIME_PROBE_FAILED"
    DEVICE_BINDING_CONFLICT = "DEVICE_BINDING_CONFLICT"
    BIND_CONTEXT_FAILED = "BIND_CONTEXT_FAILED"
    PREPARE_DATA_FAILED = "PREPARE_DATA_FAILED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    METRIC_CONTRACT_VIOLATION = "METRIC_CONTRACT_VIOLATION"
    ARTIFACT_UPLOAD_FAILED = "ARTIFACT_UPLOAD_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class StepPipelineError(RuntimeError):
    def __init__(
        self,
        *,
        code: StepErrorCode,
        stage: StepStage,
        message: str,
        cause: Exception | None = None,
    ) -> None:
        self.code = code
        self.stage = stage
        self.message = str(message or "unknown error")
        self.cause = cause
        super().__init__(self.to_user_message())

    def to_user_message(self) -> str:
        return f"[{self.code.value}] {self.message} (stage={self.stage.value})"


def infer_error_code_from_exception(
    exc: Exception,
    *,
    default: StepErrorCode,
) -> StepErrorCode:
    text = str(exc or "").upper()
    if "PROFILE_UNSATISFIED" in text:
        return StepErrorCode.PROFILE_UNSATISFIED
    if "DEVICE_BINDING_CONFLICT" in text:
        return StepErrorCode.DEVICE_BINDING_CONFLICT
    if "RUNTIME_PROBE_FAILED" in text:
        return StepErrorCode.RUNTIME_PROBE_FAILED
    if "CONFIG" in text and "RESOLVE" in text:
        return StepErrorCode.CONFIG_RESOLVE_FAILED
    if "VALIDATE" in text or "VALIDATION" in text:
        return StepErrorCode.PARAM_VALIDATE_FAILED
    if "METRIC_CONTRACT_VIOLATION" in text or "PLUGINMETRICCONTRACTERROR" in text:
        return StepErrorCode.METRIC_CONTRACT_VIOLATION
    return default


def wrap_stage_error(
    *,
    stage: StepStage,
    default_code: StepErrorCode,
    exc: Exception,
    message: str,
) -> StepPipelineError:
    if isinstance(exc, StepPipelineError):
        return exc
    code = infer_error_code_from_exception(exc, default=default_code)
    return StepPipelineError(code=code, stage=stage, message=message, cause=exc)
