from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Saki Model Runtime"
    RUNTIME_VERSION: str = "0.1.0"

    # Saki API Configuration (HTTP internal IR)
    SAKI_BASE_URL: str = "http://localhost:8000"
    INTERNAL_TOKEN: str = "dev-secret"
    HTTP_TIMEOUT_SEC: int = 30
    
    # gRPC Agent Configuration
    API_GRPC_TARGET: str = "localhost:50051"
    RUNTIME_AGENT_ID: str = "runtime-agent-1"
    HEARTBEAT_INTERVAL_SEC: int = 10
    COMMAND_TIMEOUT_SEC: int = 300

    # Runtime Configuration
    RUNS_DIR: str = "runs"
    
    model_config = SettingsConfigDict(case_sensitive=True, env_file=".env")

settings = Settings()
