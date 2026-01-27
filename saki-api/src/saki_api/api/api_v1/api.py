from saki_api.api.api_v1.endpoints import (
    system, login, users, roles
)
from saki_api.core.router import create_api_router

# 使用 AutoWrapAPIRoute 创建 API 路由器
api_router = create_api_router()
api_router.include_router(system.router, prefix="/system", tags=["system"])
api_router.include_router(login.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(roles.router, prefix="/roles", tags=["roles"])
