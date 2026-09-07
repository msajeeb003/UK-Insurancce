"""
LLM provider router.

The pipeline calls `extract_quote_fields` and never knows which provider
ran — both return the same validated `QuoteExtraction` from the same shared
prompt, so switching providers cannot change the extraction contract.

Selection (LLM_PROVIDER in .env):
  - "openai" / "anthropic"  use that provider explicitly
  - "auto" (default)        OpenAI when OPENAI_API_KEY is set, else the
                            Claude API when ANTHROPIC_API_KEY is set,
                            else a clear 503

The client's current scope: OpenAI has no credits yet, so `.env` pins
LLM_PROVIDER=anthropic (Claude Haiku). Flipping back later is a one-line
config change, not code.
"""

import logging

from app.core.config import get_settings
from app.core.errors import ConfigurationError
from app.llm.anthropic_extractor import extract_with_anthropic
from app.llm.openai_extractor import extract_with_openai
from app.models.schemas import QuoteExtraction

logger = logging.getLogger(__name__)


def resolve_provider() -> str:
    """The provider that would serve the next extraction. Raises when none."""
    settings = get_settings()
    if settings.llm_provider != "auto":
        return settings.llm_provider
    if settings.openai_api_key.get_secret_value():
        return "openai"
    if settings.anthropic_api_key.get_secret_value():
        return "anthropic"
    raise ConfigurationError(
        "No LLM provider is configured — set OPENAI_API_KEY or "
        "ANTHROPIC_API_KEY in .env (or pin one with LLM_PROVIDER)."
    )


def active_model_label() -> str:
    """Provider-qualified model name for response metadata. Never raises."""
    settings = get_settings()
    try:
        provider = resolve_provider()
    except ConfigurationError:
        return "unconfigured"
    model = (
        settings.anthropic_model if provider == "anthropic" else settings.openai_model
    )
    return f"{provider}:{model}"


def extract_quote_fields(tagged_document_text: str) -> QuoteExtraction:
    """Dispatch extraction to the configured provider."""
    provider = resolve_provider()
    if provider == "anthropic":
        return extract_with_anthropic(tagged_document_text)
    return extract_with_openai(tagged_document_text)
