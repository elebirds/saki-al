from fastapi import Header

from saki_api.core.config import settings
from saki_api.core.exceptions import ForbiddenAppException


async def verify_internal_token(x_internal_token: str = Header(...)):
    if x_internal_token != settings.INTERNAL_TOKEN:
        raise ForbiddenAppException("Invalid internal token")
    return x_internal_token
