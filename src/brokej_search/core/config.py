from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BROKEJ_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/brokej.db"
    source_storage: Path = Path("./data/sources")
    log_level: str = "INFO"
    http_timeout_seconds: float = Field(default=20, gt=0, le=120)
    discovery_user_agent: str = "BrokeJ-Search/0.1 (+local-job-discovery)"
    discovery_interval_minutes: int = Field(default=1440, ge=1)
    scheduler_timezone: str = "UTC"


@lru_cache
def get_settings() -> Settings:
    return Settings()
