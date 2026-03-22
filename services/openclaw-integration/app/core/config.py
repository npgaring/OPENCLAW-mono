"""Settings from environment. Copy example.env to .env."""
import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse, urlunparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,  # Vercel and most envs use UPPERCASE (DATABASE_URL, etc.)
        env_file=_ENV_PATH if _ENV_PATH.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: Optional[str] = Field(default=None, description="PostgreSQL URL (postgres:// or postgresql://); optional on serverless until configured")
    openclaw_base_url: Optional[str] = Field(default=None, description="OpenClaw Gateway base URL (e.g. https://api.cdopenclaw.com)")
    openclaw_api_key: Optional[str] = Field(default=None, description="Bearer token for OpenClaw Gateway (POST .../v1/responses). Required by OpenClaw.")
    integration_api_key: Optional[str] = Field(default=None, description="Authorization for our API: callers use Bearer <this> to access /task, /audit, /gate, /status. Also used to sign execution tokens.")
    app_env: str = Field(default="development", description="development | preview | production")
    log_level: str = Field(default="info", description="Log level")
    uato_default_trust_level: str = Field(
        default="HIGH",
        description="UATO trust level when request omits uato hints (HIGH|LOW). Default HIGH preserves legacy admissibility.",
    )
    uato_default_authority_level: str = Field(
        default="HIGH",
        description="UATO authority level when request omits uato hints (HIGH|LOW). Default HIGH preserves legacy admissibility.",
    )
    invariant_e_require_budget_limit: bool = Field(
        default=False,
        description="If true, Invariant-E denies dispatch when spec has no non-empty budget_limit (extra field on integration spec).",
    )
    invariant_e_allowed_capabilities_extra: Optional[str] = Field(
        default=None,
        description="Comma-separated extra execution capabilities (op:deploy or deploy) beyond IDENTITY_ALLOWED_OPERATIONS for Invariant-E.",
    )
    openai_flow_enabled: bool = Field(
        default=False,
        description="Enable opt-in OpenAI Vessel + Invariant-C + Substrate Adapter routes.",
    )
    openai_api_key: Optional[str] = Field(
        default=None,
        description="OpenAI API key for POST /openai/plan (Bearer auth to api.openai.com).",
    )
    openai_plan_model: str = Field(
        default="gpt-5.4-mini",
        description="OpenAI model used by the bounded plan vessel.",
    )
    openai_plan_timeout_seconds: int = Field(
        default=30,
        description="HTTP timeout (seconds) for OpenAI plan generation.",
    )
    openai_plan_max_retries: int = Field(
        default=1,
        description="Retry attempts for transient OpenAI vessel upstream failures.",
    )
    approval_request_ttl_hours: int = Field(
        default=72,
        description="Default lifetime for PENDING approval requests (expiry enforced on approve/resume).",
    )
    # P0 governance: bypass surfaces (see docs/governance-backend.md)
    # TEST_EXECUTE_ENABLED: unset = allowed in non-production, blocked in production unless "true"
    # TASK_CONTINUE_ENABLED: unset = true; set "false" to disable POST /task/{id}/continue entirely

    def get_database_url_normalized(self) -> str:
        """Convert to postgresql+asyncpg and strip sslmode into attribute."""
        url = self.database_url or ""
        if url.startswith("postgres://") or url.startswith("postgresql://"):
            url = re.sub(r"^postgres(ql)?://", "postgresql+asyncpg://", url)
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            self._db_sslmode = (qs.get("sslmode") or [None])[0]
            for p in ("sslmode", "channel_binding"):
                qs.pop(p, None)
            new_query = "&".join(f"{k}={v[0]}" for k, v in sorted(qs.items()) if v)
            url = urlunparse(parsed._replace(query=new_query))
        return url

    @property
    def db_sslmode(self) -> Optional[str]:
        if not hasattr(self, "_db_sslmode"):
            parsed = urlparse(self.database_url or "")
            qs = parse_qs(parsed.query)
            self._db_sslmode = (qs.get("sslmode") or [None])[0]
        return getattr(self, "_db_sslmode", None)

    def allow_test_execute_route(self) -> bool:
        """Non-governed OpenResponses proxy; off in production unless TEST_EXECUTE_ENABLED=true."""
        explicit = os.environ.get("TEST_EXECUTE_ENABLED")
        if explicit is not None:
            return explicit.strip().lower() in ("1", "true", "yes")
        env = (self.app_env or "").lower()
        return env not in ("production", "prod")

    def allow_task_continue_route(self) -> bool:
        """Follow-up execution without full re-gate; set TASK_CONTINUE_ENABLED=false to disable."""
        explicit = os.environ.get("TASK_CONTINUE_ENABLED")
        if explicit is not None:
            return explicit.strip().lower() not in ("0", "false", "no", "off")
        return True


settings = Settings()
