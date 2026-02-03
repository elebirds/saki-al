from fastapi import APIRouter

from saki_api.api.api_v1.endpoints import (
    system, auth, users, roles, permissions, asset, dataset, sample
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
