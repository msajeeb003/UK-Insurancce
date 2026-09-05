"""API contract tests — the OpenAI step is stubbed, everything else is real."""

import pytest
from fastapi.testclient import TestClient

import app.services.pipeline as pipeline_mod
from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert set(body) == {"status", "openai_configured", "azure_configured"}


def test_security_headers(client):
    res = client.get("/health")
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"


def test_frontend_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Quote Comparison Tool" in res.text


def test_rejects_non_pdf(client):
    res = client.post(
        "/extract-quote", files={"file": ("notes.txt", b"hello", "text/plain")}
    )
    assert res.status_code == 415


def test_rejects_empty_file(client):
    res = client.post(
        "/extract-quote", files={"file": ("empty.pdf", b"", "application/pdf")}
    )
    assert res.status_code == 400


def test_rejects_garbage_pdf(client):
    res = client.post(
        "/extract-quote", files={"file": ("bad.pdf", b"not a pdf", "application/pdf")}
    )
    assert res.status_code == 422


def test_missing_api_key_is_503_without_leaking(client, digital_pdf, monkeypatch):
    from pydantic import SecretStr

    from app.core.config import get_settings
    from app.llm import openai_extractor
    monkeypatch.setattr(get_settings(), "openai_api_key", SecretStr(""))
    openai_extractor._get_client.cache_clear()
    res = client.post(
        "/extract-quote", files={"file": ("q.pdf", digital_pdf, "application/pdf")}
    )
    assert res.status_code == 503
    assert "OPENAI_API_KEY" in res.json()["detail"]
    assert "Traceback" not in res.text


def test_happy_path_with_stubbed_llm(client, digital_pdf, sample_extraction, monkeypatch):
    monkeypatch.setattr(
        pipeline_mod, "extract_quote_fields", lambda text: sample_extraction
    )
    res = client.post(
        "/extract-quote", files={"file": ("quote.pdf", digital_pdf, "application/pdf")}
    )
    assert res.status_code == 200
    body = res.json()

    assert body["meta"]["extraction_engine"] == "pymupdf"
    assert body["meta"]["page_count"] == 2
    assert body["data"]["insurer"] == {"value": "ACME Credit Insurance plc", "page": 1}
    # The sanitizer must have cleared the hallucinated page citation.
    assert body["data"]["indemnity"] == {"value": "90%", "page": None}
    # Ignored fields must not exist in the response at all.
    assert "type_of_policy" not in body["data"]
    assert "debt_collection_support" not in body["data"]


def test_unexpected_error_is_opaque_502(client, digital_pdf, monkeypatch):
    def boom(text):
        raise RuntimeError("internal secret: /etc/passwd")
    monkeypatch.setattr(pipeline_mod, "extract_quote_fields", boom)
    res = client.post(
        "/extract-quote", files={"file": ("q.pdf", digital_pdf, "application/pdf")}
    )
    assert res.status_code == 502
    assert "internal secret" not in res.text
