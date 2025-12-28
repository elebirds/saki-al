from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Saki Model Runtime"
    API_V1_STR: str = "/api/v1"
    
    # Saki API Configuration
    SAKI_API_URL: str = "http://localhost:8000/api/v1"
    SAKI_API_KEY: Optional[str] = None

    # Internal API Configuration
    SAKI_BASE_URL: str = "http://localhost:8000"
    INTERNAL_TOKEN: str = "dev-secret"
    HTTP_TIMEOUT_SEC: int = 30
    
    # Runtime Configuration
    RUNS_DIR: str = "runs"
    
    model_config = SettingsConfigDict(case_sensitive=True, env_file=".env")

settings = Settings()
