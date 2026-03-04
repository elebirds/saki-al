from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    EXECUTOR_ID: str = "executor-1"
    EXECUTOR_VERSION: str = "2.0.0"

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
    LOG_COLOR_MODE: str = "auto"

    ENABLE_COMMAND_STDIN: bool = True
    DISCONNECT_FORCE_WAIT_SEC: int = 20
    PLUGINS_DIR: str = "../saki-plugins"
    PLUGIN_VENV_AUTO_SYNC: bool = True
    PLUGIN_MM_EXT_AUTO_REPAIR: bool = True
    PLUGIN_MM_EXT_AUTO_REPAIR_TIMEOUT_SEC: int = 1200
    PLUGIN_CUDA_TOOLCHAIN_AUTO_ALIGN: bool = True
    PLUGIN_CUDA_TOOLCHAIN_AUTO_INSTALL_NVCC: bool = True
    PLUGIN_CUDA_TOOLCHAIN_ALIGN_TIMEOUT_SEC: int = 300
    PLUGIN_CUDA_TOOLCHAIN_SEARCH_PATHS: str = "/usr/local,/opt"
    PLUGIN_WORKER_STARTUP_TIMEOUT_SEC: int = 10
    PLUGIN_WORKER_TERM_TIMEOUT_SEC: int = 5
    PLUGIN_WORKER_REQ_POLL_INTERVAL_MS: int = 200
    PLUGIN_WORKER_IPC_DIR: str = "/tmp/saki"

    ROUND_SHARED_CACHE_ENABLED: bool = True
    STRICT_TRAIN_MODEL_HANDOFF: bool = True

    @field_validator("LOG_COLOR_MODE", mode="before")
    @classmethod
    def parse_log_color_mode(cls, v: str | None) -> str:
        mode = str(v or "auto").strip().lower()
        if mode not in {"auto", "on", "off"}:
            return "auto"
        return mode

    model_config = SettingsConfigDict(case_sensitive=True, env_file=".env")


settings = Settings()
