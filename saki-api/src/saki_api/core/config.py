from typing import List

from pydantic import field_validator
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
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/saki"
    SQL_ECHO: bool = False

    # Connection pool settings (only used for non-SQLite databases)
    POOL_SIZE: int = 20
    MAX_OVERFLOW: int = 10
    POOL_RECYCLE: int = 1800  # 30 minutes

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_db_connection(cls, v: str) -> str:
        """
        自动将同步数据库 URL 转换为异步驱动 URL。
        
        - sqlite:/// -> sqlite+aiosqlite:///
        - postgresql:// -> postgresql+psycopg://
        """
        if isinstance(v, str):
            if v.startswith("sqlite:///"):
                return v.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
            if v.startswith("postgresql://"):
                # 显式使用 psycopg 驱动 (v3)
                return v.replace("postgresql://", "postgresql+psycopg://", 1)
        return v

    @field_validator("RUNTIME_EXECUTOR_ALLOWLIST", mode="before")
    @classmethod
    def parse_runtime_allowlist(cls, v: str | list[str] | None) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [item.strip() for item in v if item and item.strip()]
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                return []
            if stripped.startswith("[") and stripped.endswith("]"):
                import json
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except Exception:
                    pass
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return []

    # MinIO Object Storage Configuration
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_SECURE: bool = False
    MINIO_BUCKET_NAME: str = "saki-data"

    # Redis (Working Area Cache)
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_KEY_PREFIX: str = "saki"
    REDIS_WORKING_TTL_SECONDS: int = 86400  # 24 hours

    # Runtime control plane
    INTERNAL_TOKEN: str = "dev-secret"
    RUNTIME_GRPC_BIND: str = "0.0.0.0:50051"
    RUNTIME_HEARTBEAT_TIMEOUT_SEC: int = 30
    RUNTIME_DISPATCH_INTERVAL_SEC: int = 3
    RUNTIME_UPLOAD_URL_EXPIRE_HOURS: int = 2
    RUNTIME_MAX_RETRY_COUNT: int = 2
    RUNTIME_RETRY_BASE_DELAY_SEC: int = 10
    RUNTIME_ASSIGN_ACK_TIMEOUT_SEC: int = 30
    RUNTIME_STREAM_REJECT_CLOSE: bool = True
    RUNTIME_EXECUTOR_ALLOWLIST: List[str] = []
    RUNTIME_REQUEST_IDEMPOTENCY_TTL_SEC: int = 600
    RUNTIME_REQUEST_IDEMPOTENCY_MAX_ENTRIES: int = 2048

    # FEDO LUT local cache
    LUT_CACHE_DIR: str = "./data/lut_cache"

    # Security
    SECRET_KEY: str = "YOUR_SUPER_SECRET_KEY_CHANGE_ME_IN_PRODUCTION"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    class Config:
        case_sensitive = True
        env_file = ".env"  # 允许从根目录的 .env 文件读取变量


settings = Settings()
