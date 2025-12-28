from fastapi import APIRouter
from saki_runtime.api.v1.endpoints import plugins, jobs, query

api_router = APIRouter()

api_router.include_router(plugins.router, prefix="/plugins", tags=["plugins"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(query.router, prefix="/query", tags=["query"])

