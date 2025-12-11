from fastapi import FastAPI
from saki_runtime.core.config import settings
from saki_runtime.api.v1.router import api_router

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    description="Saki Model Runtime Service",
    version="0.1.0",
)

app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "saki-runtime"}
