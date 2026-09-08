"""LLM provider routing — both providers behind one extraction contract."""

import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from app.core.errors import ConfigurationError
from app.llm import router


@pytest.fixture
def settings(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "auto")
    monkeypatch.setattr(s, "openai_api_key", SecretStr(""))
    monkeypatch.setattr(s, "anthropic_api_key", SecretStr(""))
    return s


def test_auto_prefers_openai_when_its_key_is_set(settings, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("sk-x"))
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("sk-ant-x"))
    assert router.resolve_provider() == "openai"
    assert router.active_model_label() == f"openai:{settings.openai_model}"


def test_auto_falls_back_to_anthropic(settings, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("sk-ant-x"))
    assert router.resolve_provider() == "anthropic"
    assert router.active_model_label() == "anthropic:claude-haiku-4-5"


def test_explicit_provider_pins_regardless_of_other_keys(settings, monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("sk-x"))
    assert router.resolve_provider() == "anthropic"


def test_no_keys_raises_config_error(settings):
    with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
        router.resolve_provider()
    assert router.active_model_label() == "unconfigured"


def test_dispatch_calls_the_selected_provider(settings, monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    calls = []
    monkeypatch.setattr(router, "extract_with_anthropic",
                        lambda text: calls.append(("anthropic", text)) or "A")
    monkeypatch.setattr(router, "extract_with_openai",
                        lambda text: calls.append(("openai", text)) or "O")
    assert router.extract_quote_fields("doc") == "A"
    assert calls == [("anthropic", "doc")]
