from fastapi import APIRouter

from saki_api.api.api_v1.endpoints import (
    system, auth, users, roles, permissions, asset, dataset, sample
)
from saki_api.api.api_v1.endpoints.l2 import project, label, commit, branch, annotation
from saki_api.api.api_v1.endpoints.l3 import (
    job as l3_job,
    query as l3_query,
    runtime as l3_runtime,
    loop_control as l3_loop_control,
    model as l3_model,
)

api_router = APIRouter()
api_router.include_router(system.router, prefix="/system", tags=["system"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(roles.router, prefix="/roles", tags=["roles"])
api_router.include_router(permissions.router, prefix="/permissions", tags=["permissions"])
api_router.include_router(asset.router, prefix="/assets", tags=["assets"])
api_router.include_router(dataset.router, prefix="/datasets", tags=["datasets"])
api_router.include_router(sample.router, prefix="/samples", tags=["samples"])
# L2 Layer endpoints
api_router.include_router(project.router, prefix="/projects", tags=["projects"])
api_router.include_router(label.router, prefix="/labels", tags=["labels"])
api_router.include_router(commit.router, prefix="/commits", tags=["commits"])
api_router.include_router(branch.router, prefix="/branches", tags=["branches"])
api_router.include_router(annotation.router, prefix="/annotations", tags=["annotations"])
api_router.include_router(l3_job.router, prefix="", tags=["jobs"])
api_router.include_router(l3_query.router, prefix="", tags=["loops", "jobs"])
api_router.include_router(l3_runtime.router, prefix="", tags=["runtime"])
api_router.include_router(l3_loop_control.router, prefix="", tags=["loops", "annotation-batches"])
api_router.include_router(l3_model.router, prefix="", tags=["models"])
