"""Settings and project paths."""
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,  # allow DATABASE_URL in uppercase on Vercel
        env_file=_ENV_PATH if _ENV_PATH.exists() else None,
        env_file_encoding="utf-8",
        extra="forbid",
    )

    database_url: str = Field(
        default="sqlite+aiosqlite:///./dude_x.db",
        description="Async DB URL (PostgreSQL or SQLite)",
    )
    app_env: str = Field(default="development", description="APP_ENV")
    log_level: str = Field(default="info", description="Log level")
    dude_x_dusky_api_key: str = Field(
        default="",
        description="API key for X-API-Key header (required at runtime)",
    )


settings = Settings()
