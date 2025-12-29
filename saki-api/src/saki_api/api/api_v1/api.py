from fastapi import APIRouter

from saki_api.api.api_v1.endpoints import (
    projects, login, users, system, configs, 
    samples, annotations, al, model_versions, datasets, labels
)

api_router = APIRouter()
api_router.include_router(system.router, prefix="/system", tags=["system"])
api_router.include_router(login.router, tags=["login"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(datasets.router, prefix="/datasets", tags=["datasets"])
api_router.include_router(labels.router, prefix="/datasets", tags=["labels"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(samples.router, prefix="/samples", tags=["samples"])
api_router.include_router(annotations.router, prefix="/annotations", tags=["annotations"])
api_router.include_router(al.router, prefix="/active-learning", tags=["active-learning"])
api_router.include_router(model_versions.router, prefix="/model-versions", tags=["model-versions"])
api_router.include_router(configs.router, prefix="/configs", tags=["configs"])
