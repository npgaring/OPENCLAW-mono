"""Settings and project paths."""
from pathlib import Path

from pydantic import Field, field_validator
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
    cors_origins: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Allowed CORS origins. Use '*' to allow all.",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value):
        if value is None:
            return ["*"]
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return ["*"]
            return [item.strip() for item in raw.split(",") if item.strip()]
        return value


settings = Settings()
