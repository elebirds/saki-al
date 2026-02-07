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

    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"
    LOG_FILE_NAME: str = "executor.log"
    LOG_MAX_BYTES: int = 20 * 1024 * 1024
    LOG_BACKUP_COUNT: int = 5

    ENABLE_COMMAND_STDIN: bool = True

    model_config = SettingsConfigDict(case_sensitive=True, env_file=".env")


settings = Settings()
