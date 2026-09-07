"""
LLM extraction via the OpenAI Responses API with Structured Outputs.

`client.responses.parse(..., text_format=QuoteExtraction)` compiles the
Pydantic model into a strict JSON schema, so the model is physically unable
to return anything but the fixed structure. The prompt (shared with every
provider — see app/llm/prompt.py) carries the business rules the schema
alone cannot express.
"""

import logging
from functools import lru_cache

from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

from app.core.config import get_settings
from app.core.errors import ConfigurationError, UpstreamServiceError
from app.llm.prompt import build_system_prompt, build_user_message
from app.models.schemas import QuoteExtraction

logger = logging.getLogger(__name__)


@lru_cache
def _get_client() -> OpenAI:
    """One client per process — reuses the HTTP connection pool."""
    settings = get_settings()
    if not settings.openai_api_key.get_secret_value():
        raise ConfigurationError("OPENAI_API_KEY is not configured — set it in .env.")
    return OpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        timeout=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
    )


def extract_with_openai(tagged_document_text: str) -> QuoteExtraction:
    """
    Send page-tagged document text to OpenAI and get back a validated
    `QuoteExtraction` instance.

    Blocking call — the pipeline runs it in a worker thread.
    """
    settings = get_settings()
    client = _get_client()

    try:
        response = client.responses.parse(
            model=settings.openai_model,
            instructions=build_system_prompt(),
            input=[{"role": "user", "content": build_user_message(tagged_document_text)}],
            text_format=QuoteExtraction,  # <- strict Structured Output schema
            temperature=0,                # deterministic extraction
        )
    except AuthenticationError as exc:
        raise ConfigurationError(
            "OpenAI rejected the API key — check OPENAI_API_KEY in .env."
        ) from exc
    except RateLimitError as exc:
        # Covers true rate limits AND exhausted credits (insufficient_quota).
        logger.error("OpenAI rate/credit limit: %s", exc)
        raise UpstreamServiceError(
            "OpenAI refused the request — rate limit reached or no credits "
            "remaining on the account. Check the billing page."
        ) from exc
    except (APITimeoutError, APIConnectionError) as exc:
        logger.error("OpenAI connection problem: %s", exc)
        raise UpstreamServiceError(
            "Could not reach OpenAI (timeout or network error). Try again."
        ) from exc

    if response.output_parsed is None:
        # Happens if the model refused or the output was cut short. Log the
        # raw payload for diagnosis but never return it to the client.
        logger.error(
            "OpenAI returned no parsed output (status=%r). Raw text: %r",
            response.status, response.output_text[:500],
        )
        raise UpstreamServiceError(
            "The AI model returned no usable extraction for this document. "
            "Try again, or check the server logs for details."
        )

    logger.info("OpenAI extraction complete (model=%s)", settings.openai_model)
    return response.output_parsed
