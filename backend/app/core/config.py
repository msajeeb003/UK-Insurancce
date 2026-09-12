"""
Central configuration for the Quote Comparison Tool backend.

All secrets are read from environment variables (or a local `.env` file).
Copy `.env.example` -> `.env` and fill in:

    OPENAI_API_KEY   -> your OpenAI key
    AZURE_ENDPOINT   -> your Azure AI Document Intelligence endpoint URL
    AZURE_KEY        -> your Azure AI Document Intelligence key

Secrets are typed as `SecretStr` so they can never leak through repr(),
logging, or error messages — use `.get_secret_value()` at the call site.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env lives at the repository root (one level above backend/), so the same
# file works no matter which directory the server or tests are run from.
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    # ── LLM provider selection ───────────────────────────────────────────
    # "auto" uses OpenAI when its key is set, else the Claude API.
    # Pin explicitly with LLM_PROVIDER=openai|anthropic in .env.
    llm_provider: Literal["auto", "openai", "anthropic"] = "auto"

    # ── OpenAI (Structured Output extraction) ────────────────────────────
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-4o-2024-08-06"
    openai_timeout_seconds: float = 120.0
    openai_max_retries: int = 2

    # ── Claude API (Anthropic SDK, structured outputs) ───────────────────
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-haiku-4-5"
    anthropic_timeout_seconds: float = 120.0
    anthropic_max_retries: int = 2

    # ── Azure AI Document Intelligence (OCR fallback) ────────────────────
    azure_endpoint: str = ""
    azure_key: SecretStr = SecretStr("")

    # ── Digital-vs-scanned detection heuristics ──────────────────────────
    # A page with fewer extractable characters than this is treated as scanned.
    digital_min_chars_per_page: int = 150
    # If at least this fraction of pages look scanned, the whole document
    # is routed to Azure OCR.
    scanned_page_ratio: float = 0.4

    # ── Storage + authentication (BRD 2.9/2.10) ──────────────────────────
    # SQLite database + uploaded documents + generated exports live here.
    # Default: <repo>/data. Point DATA_DIR elsewhere (e.g. a mounted,
    # encrypted volume) in production.
    data_dir: str = ""
    # First user, seeded on startup when the users table is empty —
    # further users are added with `python -m app.manage`.
    admin_email: str = ""
    admin_password: SecretStr = SecretStr("")
    session_ttl_hours: int = 72
    # Set COOKIE_SECURE=true behind HTTPS in production.
    cookie_secure: bool = False
    # Data retention (BRD 2.11): hard-delete projects untouched for longer
    # than this many days. 0 = disabled (keep forever) — the period is the
    # client's decision, so nothing is deleted until they set it.
    retention_days: int = 0

    # ── Backups (durability / recoverability) ───────────────────────────
    # Fernet key (url-safe base64, 32 bytes) — `python -m app.backup gen-key`.
    # Empty = backups disabled (the app runs; the pre-start hook no-ops).
    backup_encryption_key: SecretStr = SecretStr("")
    # Offsite target. Set EITHER an S3-compatible bucket OR a directory
    # (a second mounted volume, or local for testing).
    backup_s3_bucket: str = ""
    backup_s3_endpoint: str = ""      # e.g. https://<acct>.r2.cloudflarestorage.com; empty = AWS
    backup_s3_region: str = "eu-central-1"
    backup_s3_access_key: SecretStr = SecretStr("")
    backup_s3_secret_key: SecretStr = SecretStr("")
    backup_offsite_dir: str = ""      # directory offsite target (alternative to S3)
    backup_retention_daily: int = 30
    backup_retention_monthly: int = 12
    backup_alert_webhook: str = ""    # optional: POST {text} here on backup/integrity failure

    # ── Environment ──────────────────────────────────────────────────────
    # "production" turns on the strict startup checks (COOKIE_SECURE, strong
    # ADMIN_PASSWORD, an LLM key) and disables the interactive API docs.
    app_env: str = "development"

    # ── LLM data-processing posture (see docs/DATA_PROCESSING.md) ─────────
    # Confidential data only ever goes to an approved official endpoint whose
    # commercial terms exclude training. A custom base_url pointing anywhere
    # else (a proxy/aggregator) is rejected.
    llm_allowed_hosts: str = "api.anthropic.com,api.openai.com"
    # The operator sets this to true once the provider DPA / zero-retention
    # terms are filed. Required in production; a bad host fails always.
    llm_no_training_ack: bool = False

    # ── Observability ────────────────────────────────────────────────────
    sentry_dsn: str = ""              # empty = Sentry disabled (no-op)
    sentry_environment: str = "production"
    # /readyz alerts when free disk on DATA_DIR falls below this fraction.
    disk_free_min_ratio: float = 0.10

    # ── Guard rails ──────────────────────────────────────────────────────
    max_upload_mb: int = 25
    # Documents longer than this are rejected before any paid API call —
    # insurer quotes are short; a 100+ page PDF is almost always a mistake.
    max_pdf_pages: int = 60
    # Per-client-IP cap on the paid/heavy POST endpoints. 0 disables.
    rate_limit_per_minute: int = 30

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def data_path(self) -> Path:
        if self.data_dir:
            return Path(self.data_dir)
        return Path(__file__).resolve().parents[3] / "data"


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor — import this everywhere instead of Settings()."""
    return Settings()
