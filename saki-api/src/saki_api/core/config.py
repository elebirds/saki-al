from typing import List

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
    BACKEND_CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Database
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/saki"
    SQL_ECHO: bool = False

    # Storage
    UPLOAD_DIR: str = "./data/uploads"

    # MinIO Object Storage Configuration
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_SECURE: bool = False
    MINIO_BUCKET_NAME: str = "saki-data"

    # Security
    SECRET_KEY: str = "YOUR_SUPER_SECRET_KEY_CHANGE_ME_IN_PRODUCTION"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    class Config:
        case_sensitive = True


settings = Settings()
