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

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── OpenAI (Structured Output extraction) ────────────────────────────
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-4o-2024-08-06"
    openai_timeout_seconds: float = 120.0
    openai_max_retries: int = 2

    # ── Azure AI Document Intelligence (OCR fallback) ────────────────────
    azure_endpoint: str = ""
    azure_key: SecretStr = SecretStr("")

    # ── Digital-vs-scanned detection heuristics ──────────────────────────
    # A page with fewer extractable characters than this is treated as scanned.
    digital_min_chars_per_page: int = 150
    # If at least this fraction of pages look scanned, the whole document
    # is routed to Azure OCR.
    scanned_page_ratio: float = 0.4

    # ── Guard rails ──────────────────────────────────────────────────────
    max_upload_mb: int = 25
    # Documents longer than this are rejected before any paid API call —
    # insurer quotes are short; a 100+ page PDF is almost always a mistake.
    max_pdf_pages: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor — import this everywhere instead of Settings()."""
    return Settings()
