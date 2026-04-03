"""Settings and project paths."""
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"
_WORKSPACE_ENV_PATH = _PROJECT_ROOT.parent.parent / ".env"
_ENV_FILES = tuple(path for path in (_ENV_PATH, _WORKSPACE_ENV_PATH) if path.exists())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,  # allow DATABASE_URL in uppercase on Vercel
        env_file=_ENV_FILES or None,
        env_file_encoding="utf-8",
        extra="ignore",  # tolerate shared/Vercel .env keys not declared here
    )

    database_url: str = Field(
        default="sqlite+aiosqlite:///./dude_x.db",
        description="Async DB URL (PostgreSQL or SQLite)",
    )
    app_env: str = Field(default="development", description="APP_ENV")
    log_level: str = Field(default="info", description="Log level")
    integration_api_key: str = Field(
        default="",
        description="Bearer token for Authorization header (required at runtime)",
    )
    cors_origins: str = Field(
        default="*",
        description="Allowed CORS origins (comma-separated). Use '*' to allow all.",
    )
    dudex_v2_enabled: bool = Field(
        default=True,
        description="Enable governed dual-engine v2 endpoints.",
    )
    governed_v2_live_governance: bool = Field(
        default=False,
        description="When true, DUDE-X v2 governance evaluation calls openclaw-integration for authoritative lock outcomes.",
    )
    governed_v2_integration_base_url: str = Field(
        default="",
        description="Base URL for openclaw-integration service (used when governed_v2_live_governance=true).",
    )
    governed_v2_github_owner: str = Field(
        default="",
        description="Primary GitHub owner slug for auto-created repos (org or user).",
    )
    governed_v2_github_owner_type: str = Field(
        default="org",
        description="Primary GitHub owner type: org | user.",
    )
    governed_v2_github_owner_fallback: str = Field(
        default="",
        description="Fallback GitHub owner slug when primary owner is unavailable.",
    )
    governed_v2_repo_name_template: str = Field(
        default="cdmbr-{projectname}-{timestamp}",
        description="Repository/project naming template used by deterministic web executor provisioning.",
    )
    governed_v2_default_branch: str = Field(
        default="prod",
        description="Default deployment branch for generated repositories and Vercel production branch.",
    )
    governed_v2_vercel_team_id: str = Field(
        default="",
        description="Vercel team id for auto-created projects.",
    )
    governed_v2_domain_behavior: str = Field(
        default="vercel_default_only",
        description="Domain behavior for v2 deploys (vercel_default_only | custom_domains).",
    )
    governed_v2_stack_preset: str = Field(
        default="nextjs-typescript-react",
        description="Default stack preset for generated web projects.",
    )
    governed_v2_trace_logging: bool = Field(
        default=True,
        description="Enable verbose governed v2 tracing logs for debugging.",
    )
    openai_content_enabled: bool = Field(
        default=False,
        description="Enable OpenAI content enrichment in cognitive mode.",
    )
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key for content enrichment and skills engine.",
    )
    openai_content_model: str = Field(
        default="gpt-4.1-mini",
        description="OpenAI model for content enrichment.",
    )
    openai_content_timeout_seconds: int = Field(
        default=60,
        description="Timeout for OpenAI content enrichment calls.",
    )
    skills_engine_enabled: bool = Field(
        default=False,
        description="Enable skills engine for real code generation in compiler.",
    )
    skills_engine_model: str = Field(
        default="gpt-4.1-mini",
        description="OpenAI model used by the skills engine.",
    )


settings = Settings()
