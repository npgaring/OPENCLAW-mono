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
_WORKSPACE_ENV_PATH = _PROJECT_ROOT.parent.parent / ".env"
_ENV_FILES = tuple(path for path in (_ENV_PATH, _WORKSPACE_ENV_PATH) if path.exists())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,  # Vercel and most envs use UPPERCASE (DATABASE_URL, etc.)
        env_file=_ENV_FILES or None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: Optional[str] = Field(default=None, description="PostgreSQL URL (postgres:// or postgresql://); optional on serverless until configured")
    openclaw_base_url: Optional[str] = Field(default=None, description="OpenClaw Gateway base URL (e.g. https://api.cdopenclaw.com)")
    openclaw_api_key: Optional[str] = Field(default=None, description="Bearer token for OpenClaw Gateway (POST .../v1/responses). Required by OpenClaw.")
    github_token: Optional[str] = Field(
        default=None,
        description="Optional GitHub token forwarded to OpenClaw Gateway for provision_repo operations.",
    )
    github_app_id: Optional[str] = Field(
        default=None,
        description="GitHub App ID used for deterministic in-service repository provisioning.",
    )
    github_private_key: Optional[str] = Field(
        default=None,
        description="GitHub App private key PEM (supports \\n escaped newlines) for deterministic execution.",
    )
    github_installation_id: Optional[str] = Field(
        default=None,
        description="GitHub App installation ID used to exchange installation tokens.",
    )
    github_template_owner: Optional[str] = Field(
        default=None,
        description="Template repository owner used for deterministic repository generation.",
    )
    github_template_repo: Optional[str] = Field(
        default=None,
        description="Template repository name used for deterministic repository generation.",
    )
    vercel_token: Optional[str] = Field(
        default=None,
        description="Optional Vercel token forwarded to OpenClaw Gateway for provision_hosting/deploy operations.",
    )
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
        default=3,
        description="Retry attempts for transient OpenAI vessel upstream failures (429, 5xx, transport errors).",
    )
    openai_plan_retry_backoff_seconds: float = Field(
        default=1.0,
        description="Base delay (seconds) before retry; exponential backoff: base * 2^attempt.",
    )
    openai_content_model: Optional[str] = Field(
        default=None,
        description="OpenAI model for content/code generation in the deterministic executor. Falls back to openai_plan_model.",
    )
    skills_engine_model: Optional[str] = Field(
        default=None,
        description="OpenAI model used by the skills engine for code generation.",
    )
    codegen_phase1_max_tokens: int = Field(
        default=4000,
        description="Max output tokens for Phase 1 (Architect) blueprint generation.",
    )
    codegen_phase2_max_tokens: int = Field(
        default=16000,
        description="Max output tokens per Phase 2 (Builder) call.",
    )
    codegen_phase3_max_tokens: int = Field(
        default=8000,
        description="Max output tokens for Phase 3 (Inspector) AI review call.",
    )
    codegen_phase2_batch_size: int = Field(
        default=3,
        description="Number of pages per batch in Phase 2 code generation.",
    )
    vercel_poll_interval_seconds: int = Field(
        default=10,
        description="Seconds between Vercel deployment status polls.",
    )
    vercel_poll_max_wait_seconds: int = Field(
        default=300,
        description="Max seconds to wait for Vercel build to finish before timing out.",
    )
    codegen_max_fix_retries: int = Field(
        default=3,
        description="Max AI auto-fix attempts when Vercel build fails.",
    )
    governed_v2_enabled: bool = Field(
        default=True,
        description="Enable governed dual-engine v2 lock endpoints and continuity enforcement hooks.",
    )
    governed_v2_trace_logging: bool = Field(
        default=True,
        description="Enable verbose governed v2 tracing logs for debugging.",
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
