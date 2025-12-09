from typing import List, Union
from pydantic import AnyHttpUrl, validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """
    Application configuration settings.
    
    Attributes:
        PROJECT_NAME: The name of the project.
        API_V1_STR: The base URL path for V1 of the API.
        BACKEND_CORS_ORIGINS: A list of origins that are allowed to make cross-origin requests.
        DATABASE_URL: The database connection string (e.g., sqlite:///./saki.db or postgresql://user:password@localhost/dbname).
    """
    PROJECT_NAME: str = "Saki Active Learning"
    API_V1_STR: str = "/api/v1"
    
    # BACKEND_CORS_ORIGINS is a JSON-formatted list of origins
    # e.g: '["http://localhost", "http://localhost:4200", "http://localhost:3000"]'
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = ["http://localhost:3000", "http://localhost:5173"]

    # Database
    DATABASE_URL: str = "sqlite:///./saki.db"

    class Config:
        case_sensitive = True

settings = Settings()
