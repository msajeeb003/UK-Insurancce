"""
Data-processing posture for the LLM path (see docs/DATA_PROCESSING.md).

Confidential client/insurer/buyer text is only ever sent to an approved
OFFICIAL provider endpoint, whose commercial terms exclude using API data for
training. There is no per-request "no-training" header at either provider —
it is the default under their terms, and zero-retention (ZDR) is an org-level
agreement — so what the code can and does enforce is:

  1. the effective endpoint host is on the approved allowlist (a custom
     base_url pointing at a proxy/aggregator is rejected — fatal, always);
  2. the operator has acknowledged the provider DPA / ZDR is filed
     (LLM_NO_TRAINING_ACK — required in production).
"""

import logging
import os
from urllib.parse import urlparse

from app.core.config import get_settings
from app.core.errors import ConfigurationError

logger = logging.getLogger("app.startup")

# Official hosts under whose commercial terms API inputs/outputs are NOT used
# for training. The SDKs read these *_BASE_URL env vars, so an operator could
# silently repoint them — hence the check.
_DEFAULT_HOST = {"openai": "api.openai.com", "anthropic": "api.anthropic.com"}
_ENV_BASE_URL = {"openai": "OPENAI_BASE_URL", "anthropic": "ANTHROPIC_BASE_URL"}


def provider_host(provider: str) -> str:
    """The host the SDK will actually call (honouring a *_BASE_URL override)."""
    override = os.environ.get(_ENV_BASE_URL.get(provider, ""), "").strip()
    if override:
        return (urlparse(override).hostname or override).lower()
    return _DEFAULT_HOST.get(provider, provider)


def assert_no_training_posture(provider: str) -> None:
    """Fail loudly if data would go somewhere without the no-training posture.

    Bad/unapproved host: fatal in every environment. Missing DPA ack: fatal in
    production, a warning in development.
    """
    settings = get_settings()
    allowed = {h.strip().lower() for h in settings.llm_allowed_hosts.split(",") if h.strip()}
    host = provider_host(provider)
    if host not in allowed:
        raise ConfigurationError(
            f"LLM endpoint host {host!r} is not on the approved no-training "
            f"allowlist {sorted(allowed)} — refusing to send confidential data "
            "to an unvetted endpoint (check *_BASE_URL / LLM_ALLOWED_HOSTS)."
        )
    if not settings.llm_no_training_ack:
        msg = ("LLM_NO_TRAINING_ACK is not set — confirm the provider DPA / "
               "zero-retention terms are filed (docs/DATA_PROCESSING.md).")
        if settings.app_env.strip().lower() == "production":
            raise ConfigurationError(msg)
        logger.warning(msg)
