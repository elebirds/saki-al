from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from saki_runtime.core.config import settings
from saki_runtime.api.v1.router import api_router
from saki_runtime.core.exceptions import RuntimeErrorBase
from saki_runtime.core.handlers import (
    runtime_exception_handler,
    validation_exception_handler,
    general_exception_handler
)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    description="Saki Model Runtime Service",
    version="0.1.0",
)

app.add_exception_handler(RuntimeErrorBase, runtime_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# Include router directly without prefix since router has no prefix in definition
# But settings.API_V1_STR is used in main.py
app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "saki-runtime"}
