"""
Central configuration for the AI Extraction Module.

All secrets are read from environment variables (or a local `.env` file).
Copy `.env.example` -> `.env` and fill in:

    OPENAI_API_KEY   -> your OpenAI key
    AZURE_ENDPOINT   -> your Azure AI Document Intelligence endpoint URL
    AZURE_KEY        -> your Azure AI Document Intelligence key
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── OpenAI (Structured Output extraction) ────────────────────────────
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-2024-08-06"

    # ── Azure AI Document Intelligence (OCR fallback) ────────────────────
    azure_endpoint: str = ""
    azure_key: str = ""

    # ── Digital-vs-scanned detection heuristics ──────────────────────────
    # A page with fewer extractable characters than this is treated as scanned.
    digital_min_chars_per_page: int = 150
    # If at least this fraction of pages look scanned, the whole document
    # is routed to Azure OCR.
    scanned_page_ratio: float = 0.4

    # ── Upload limits ────────────────────────────────────────────────────
    max_upload_mb: int = 25

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor — import this everywhere instead of Settings()."""
    return Settings()
