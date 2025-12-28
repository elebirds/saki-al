from typing import Any, Dict, Optional
from pydantic import BaseModel

from saki_runtime.schemas.enums import JobStatus, JobType
from saki_runtime.schemas.resources import JobResources

class JobDataRef(BaseModel):
    dataset_version_id: str
    label_version_id: str

class JobCreateRequest(BaseModel):
    job_type: JobType
    project_id: str
    plugin_id: str
    data_ref: JobDataRef
    params: Dict[str, Any]
    resources: JobResources

class JobCreateResponse(BaseModel):
    request_id: str
    job_id: str
    status: JobStatus

class JobInfo(BaseModel):
    job_id: str
    job_type: JobType
    plugin_id: str
    status: JobStatus
    created_at: int
    started_at: Optional[int] = None
    ended_at: Optional[int] = None
    data_ref: JobDataRef
    params: Dict[str, Any]
    resources: JobResources
    summary: Optional[Dict[str, Any]] = None

class JobGetResponse(BaseModel):
    request_id: str
    job: JobInfo
