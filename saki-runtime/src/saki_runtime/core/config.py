from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Saki Model Runtime"
    API_V1_STR: str = "/api/v1"
    
    # Saki API Configuration
    SAKI_API_URL: str = "http://localhost:8000/api/v1"
    SAKI_API_KEY: Optional[str] = None
    
    # Runtime Configuration
    RUNS_DIR: str = "runs"
    
    class Config:
        case_sensitive = True
        env_file = ".env"

settings = Settings()
