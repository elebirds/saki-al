from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    EXECUTOR_ID: str = "executor-1"
    EXECUTOR_VERSION: str = "0.1.0"

    API_GRPC_TARGET: str = "localhost:50051"
    INTERNAL_TOKEN: str = "dev-secret"
    HEARTBEAT_INTERVAL_SEC: int = 10

    RUNS_DIR: str = "runs"
    CACHE_DIR: str = "cache"
    CACHE_MAX_BYTES: int = 500 * 1024 * 1024 * 1024  # 500 GB

    DEFAULT_GPU_IDS: str = "0"
    CPU_WORKERS: int = 4
    MEMORY_MB: int = 0

    model_config = SettingsConfigDict(case_sensitive=True, env_file=".env")


settings = Settings()
