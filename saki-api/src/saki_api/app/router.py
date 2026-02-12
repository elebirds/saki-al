from fastapi import APIRouter

from saki_api.app.module_registry import get_app_modules

api_router = APIRouter()
for module in get_app_modules():
    module.register_routes(api_router)
