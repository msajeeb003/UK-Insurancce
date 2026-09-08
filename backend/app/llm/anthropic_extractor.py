"""
LLM extraction via the Claude API (Anthropic SDK) with structured outputs.

`client.messages.parse(..., output_format=QuoteExtraction)` constrains the
response to the Pydantic schema and returns a validated instance on
`response.parsed_output` — the same guarantee the OpenAI path gives, so the
downstream pipeline (sanitize -> verify -> review -> set fields) is
provider-agnostic.

Model comes from ANTHROPIC_MODEL (default `claude-haiku-4-5`, the current
Haiku — chosen for this scope by the client); key from ANTHROPIC_API_KEY.
When no key is configured in settings, the zero-arg client lets the SDK
resolve ambient credentials (env var or an `ant auth login` profile).
"""

import logging
from functools import lru_cache

import anthropic

from app.core.config import get_settings
from app.core.errors import ConfigurationError, UpstreamServiceError
from app.llm.prompt import build_system_prompt, build_user_message
from app.models.schemas import QuoteExtraction

logger = logging.getLogger(__name__)

# The extraction JSON is small (a few KB); 8192 leaves ample headroom
# without inviting run-on output.
MAX_OUTPUT_TOKENS = 8192


@lru_cache
def _get_client() -> anthropic.Anthropic:
    """One client per process — reuses the HTTP connection pool."""
    settings = get_settings()
    key = settings.anthropic_api_key.get_secret_value()
    kwargs: dict = {
        "timeout": settings.anthropic_timeout_seconds,
        "max_retries": settings.anthropic_max_retries,
    }
    if key:
        kwargs["api_key"] = key
    # Without an explicit key the SDK resolves ANTHROPIC_API_KEY /
    # ANTHROPIC_AUTH_TOKEN / an `ant auth login` profile on its own.
    try:
        return anthropic.Anthropic(**kwargs)
    except Exception as exc:  # no ambient credentials found
        raise ConfigurationError(
            "No Claude API credentials found — set ANTHROPIC_API_KEY in .env."
        ) from exc


def extract_with_anthropic(tagged_document_text: str) -> QuoteExtraction:
    """
    Send page-tagged document text to Claude and get back a validated
    `QuoteExtraction` instance.

    Blocking call — the pipeline runs it in a worker thread.
    """
    settings = get_settings()
    client = _get_client()

    try:
        response = client.messages.parse(
            model=settings.anthropic_model,
            max_tokens=MAX_OUTPUT_TOKENS,
            # parse() exposes no temperature parameter; inject it for
            # deterministic extraction via the SDK's body escape hatch.
            extra_body={"temperature": 0},
            system=build_system_prompt(),
            messages=[
                {"role": "user", "content": build_user_message(tagged_document_text)}
            ],
            output_format=QuoteExtraction,
        )
    except anthropic.AuthenticationError as exc:
        raise ConfigurationError(
            "The Claude API rejected the key — check ANTHROPIC_API_KEY in .env."
        ) from exc
    except TypeError as exc:
        # The SDK raises TypeError at request time when it can resolve no
        # credentials at all (no key, no env var, no `ant` profile).
        if "authentication" in str(exc).lower():
            raise ConfigurationError(
                "No Claude API credentials found — set ANTHROPIC_API_KEY in .env."
            ) from exc
        raise
    except anthropic.RateLimitError as exc:
        logger.error("Claude API rate/credit limit: %s", exc)
        raise UpstreamServiceError(
            "The Claude API refused the request — rate limit reached or no "
            "credits remaining on the account. Check the billing page."
        ) from exc
    except (anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
        logger.error("Claude API connection problem: %s", exc)
        raise UpstreamServiceError(
            "Could not reach the Claude API (timeout or network error). Try again."
        ) from exc

    if response.stop_reason == "refusal":
        logger.error("Claude declined the request (stop_details=%r)",
                     getattr(response, "stop_details", None))
        raise UpstreamServiceError(
            "The AI model declined to process this document. Try again, or "
            "check the server logs for details."
        )
    if response.parsed_output is None:
        logger.error(
            "Claude returned no parsed output (stop_reason=%r)",
            response.stop_reason,
        )
        raise UpstreamServiceError(
            "The AI model returned no usable extraction for this document. "
            "Try again, or check the server logs for details."
        )

    logger.info("Claude extraction complete (model=%s)", settings.anthropic_model)
    return response.parsed_output
