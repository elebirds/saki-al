from fastapi import APIRouter

from saki_api.api.api_v1.endpoints import (
    system, auth, users, roles, permissions, asset, dataset, sample
)
from saki_api.api.api_v1.endpoints.l2 import project, label, commit, branch, annotation

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
api_router.include_router(label.router, prefix="/api/v1/labels", tags=["labels"])
api_router.include_router(commit.router, prefix="/api/v1/commits", tags=["commits"])
api_router.include_router(branch.router, prefix="/api/v1/branches", tags=["branches"])
api_router.include_router(annotation.router, prefix="/api/v1/annotations", tags=["annotations"])
