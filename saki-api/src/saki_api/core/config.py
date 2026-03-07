from pathlib import Path
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_API_ROOT = Path(__file__).resolve().parents[3]
_WORKSPACE_ROOT = _API_ROOT.parent
_ENV_FILES = (
    str(_API_ROOT / ".env"),
    str(_WORKSPACE_ROOT / ".env"),
)


class Settings(BaseSettings):
    """
    Application configuration settings.
    
    Attributes:
        PROJECT_NAME: The name of the project.
        API_V1_STR: The base URL path for V1 of the API.
        BACKEND_CORS_ORIGINS: A list of origins that are allowed to make cross-origin requests.
        DATABASE_URL: The database connection string (PostgreSQL only).
    """
    PROJECT_NAME: str = "Saki Active Learning"
    API_V1_STR: str = "/api/v1"

    # BACKEND_CORS_ORIGINS is a JSON-formatted list of origins
    # e.g: '["http://localhost", "http://localhost:4200", "http://localhost:3000"]'
    BACKEND_CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/saki"
    SQL_ECHO: bool = False

    # Connection pool settings
    POOL_SIZE: int = 20
    MAX_OVERFLOW: int = 10
    POOL_RECYCLE: int = 1800  # 30 minutes

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_db_connection(cls, v: str) -> str:
        """
        强制使用 PostgreSQL，并统一转换为 psycopg 异步驱动 URL。
        """
        if isinstance(v, str):
            raw = v.strip()
            if raw.startswith("postgres://"):
                return raw.replace("postgres://", "postgresql+psycopg://", 1)
            if raw.startswith("postgresql+psycopg://"):
                return raw
            if raw.startswith("postgresql://"):
                # 显式使用 psycopg 驱动 (v3)
                return raw.replace("postgresql://", "postgresql+psycopg://", 1)
            raise ValueError("DATABASE_URL 必须使用 PostgreSQL（postgresql:// 或 postgresql+psycopg://）。")
        return v

    @field_validator("LOG_COLOR_MODE", mode="before")
    @classmethod
    def parse_log_color_mode(cls, v: str | None) -> str:
        mode = str(v or "auto").strip().lower()
        if mode not in {"auto", "on", "off"}:
            return "auto"
        return mode

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

    # Importing
    IMPORT_PREVIEW_TTL_MINUTES: int = 30
    IMPORT_UPLOAD_SESSION_TTL_MINUTES: int = 120
    IMPORT_UPLOAD_MULTIPART_THRESHOLD_BYTES: int = 64 * 1024 * 1024
    IMPORT_UPLOAD_PART_SIZE_BYTES: int = 16 * 1024 * 1024
    IMPORT_UPLOAD_MAX_PARTS_PER_SIGN: int = 100
    IMPORT_MAX_ZIP_BYTES: int = 2 * 1024 * 1024 * 1024  # 2GB
    IMPORT_MAX_ENTRIES: int = 100000
    IMPORT_ALLOWED_IMAGE_EXTS: List[str] = [
        ".jpg",
        ".jpeg",
        ".png",
        ".bmp",
        ".webp",
        ".tif",
        ".tiff",
    ]
    IMPORT_MAX_CONCURRENT_TASKS: int = 1
    IMPORT_TASK_RETENTION_HOURS: int = 72
    IMPORT_EVENT_HEARTBEAT_SECONDS: int = 10

    # Exporting
    EXPORT_FRONTEND_MAX_TOTAL_BYTES: int = 1024 * 1024 * 1024  # 1GB
    EXPORT_ASSET_URL_EXPIRE_HOURS: int = 2

    # Runtime control plane
    INTERNAL_TOKEN: str = "dev-secret"
    RUNTIME_DOMAIN_GRPC_BIND: str = "0.0.0.0:50053"
    RUNTIME_UPLOAD_URL_EXPIRE_HOURS: int = 2
    RUNTIME_DOWNLOAD_URL_EXPIRE_HOURS: int = 2
    RUNTIME_MAX_RETRY_COUNT: int = 2
    RUNTIME_DOMAIN_GRPC_SERVER_ENABLED: bool = True

    # External dispatcher control-plane bridge
    DISPATCHER_ADMIN_TARGET: str = "0.0.0.0:50052"
    DISPATCHER_ADMIN_TIMEOUT_SEC: int = 5

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"
    LOG_FILE_NAME: str = "api.log"
    LOG_MAX_BYTES: int = 20 * 1024 * 1024
    LOG_BACKUP_COUNT: int = 5
    LOG_COLOR_MODE: str = "auto"
    RBAC_DEBUG_LOG: bool = True

    # FEDO LUT local cache
    LUT_CACHE_DIR: str = "./data/lut_cache"

    # Security
    SECRET_KEY: str = "YOUR_SUPER_SECRET_KEY_CHANGE_ME_IN_PRODUCTION"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    model_config = SettingsConfigDict(case_sensitive=True, env_file=_ENV_FILES)


settings = Settings()
