from fastapi import APIRouter

from saki_api.api.internal import runtime

internal_router = APIRouter()
internal_router.include_router(runtime.router, tags=["internal-runtime"])
