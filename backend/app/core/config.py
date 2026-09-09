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
