from fastapi import APIRouter
from api.api_v1.endpoints import projects, login, users, system, configs, specialized, samples

api_router = APIRouter()
api_router.include_router(system.router, prefix="/system", tags=["system"])
api_router.include_router(login.router, tags=["login"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(samples.router, prefix="/samples", tags=["samples"])
api_router.include_router(configs.router, prefix="/configs", tags=["configs"])
api_router.include_router(specialized.router, prefix="/specialized", tags=["specialized"])

