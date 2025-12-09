from fastapi import APIRouter
from app.api.api_v1.endpoints import projects

api_router = APIRouter()
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
