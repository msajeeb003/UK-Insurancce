"""No-training / no-retention posture + payload minimisation."""


import pytest

from app.core.config import get_settings
from app.core.errors import ConfigurationError
from app.llm import policy


def test_official_host_is_allowed(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.setattr(get_settings(), "llm_no_training_ack", True)
    policy.assert_no_training_posture("anthropic")     # no raise


def test_proxy_host_is_rejected(monkeypatch):
    # Repointing the SDK at a proxy/aggregator must fail loudly, always.
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://llm-proxy.example.com/v1")
    monkeypatch.setattr(get_settings(), "llm_no_training_ack", True)
    with pytest.raises(ConfigurationError, match="allowlist"):
        policy.assert_no_training_posture("anthropic")


def test_missing_ack_is_fatal_in_production(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    s = get_settings()
    monkeypatch.setattr(s, "app_env", "production")
    monkeypatch.setattr(s, "llm_no_training_ack", False)
    with pytest.raises(ConfigurationError, match="NO_TRAINING_ACK"):
        policy.assert_no_training_posture("anthropic")


def test_missing_ack_is_warning_in_dev(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    s = get_settings()
    monkeypatch.setattr(s, "app_env", "development")
    monkeypatch.setattr(s, "llm_no_training_ack", False)
    policy.assert_no_training_posture("anthropic")      # warns, no raise


def test_provider_host_honours_base_url_override(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    assert policy.provider_host("openai") == "api.openai.com"
    monkeypatch.setenv("OPENAI_BASE_URL", "https://evil.example.com")
    assert policy.provider_host("openai") == "evil.example.com"


# ── Payload minimisation ────────────────────────────────────────────────────

def test_user_message_sends_only_the_fenced_document():
    """Only the document text goes to the LLM — no filename, user id,
    project id, or other metadata is appended."""
    from app.llm.prompt import build_user_message

    doc = "=== PAGE 1 ===\nInsurer: ACME\nIndemnity: 90%"
    msg = build_user_message(doc)
    assert doc in msg
    # nothing beyond the instruction wrapper + the fenced document
    stripped = msg.replace(doc, "")
    for leak in ("filename", "user", "project", "email", "session", ".pdf"):
        assert leak not in stripped.lower()


def test_system_prompt_carries_only_config_not_client_data():
    """The system prompt is rules + the terminology library + the standing
    insurer list — all client-maintained config, no per-request PII."""
    from app.llm.prompt import build_system_prompt

    prompt = build_system_prompt()
    assert "MAPPING LIBRARY" in prompt and "STRICT rules" in prompt
