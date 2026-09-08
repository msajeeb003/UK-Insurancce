"""Scanned-PDF engine routing (BRD 2.2): Azure when configured, else the
open-source Docling fallback; explicit overrides always win."""

from pydantic import SecretStr

from app.core.config import get_settings
from app.services.pipeline import _scanned_engine


def _clear_azure(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_endpoint", "")
    monkeypatch.setattr(settings, "azure_key", SecretStr(""))
    return settings


def test_scanned_defaults_to_docling_without_azure(monkeypatch):
    _clear_azure(monkeypatch)
    assert _scanned_engine("auto") == "docling"


def test_scanned_prefers_azure_when_configured(monkeypatch):
    settings = _clear_azure(monkeypatch)
    monkeypatch.setattr(settings, "azure_endpoint", "https://x.example.com/")
    monkeypatch.setattr(settings, "azure_key", SecretStr("k"))
    assert _scanned_engine("auto") == "azure"


def test_explicit_override_beats_configuration(monkeypatch):
    settings = _clear_azure(monkeypatch)
    monkeypatch.setattr(settings, "azure_endpoint", "https://x.example.com/")
    monkeypatch.setattr(settings, "azure_key", SecretStr("k"))
    assert _scanned_engine("docling") == "docling"
    _clear_azure(monkeypatch)
    assert _scanned_engine("azure") == "azure"


def test_scanned_pdf_uses_docling_via_api(sparse_pdf, sample_extraction, monkeypatch):
    from fastapi.testclient import TestClient

    import app.services.pipeline as pipeline_mod
    from app.extraction.base import PageText
    from app.main import app

    _clear_azure(monkeypatch)
    monkeypatch.setattr(
        pipeline_mod, "extract_pages_docling",
        lambda data: [PageText(1, "OCR TEXT Insurable Turnover GBP 8,500,000")],
    )
    monkeypatch.setattr(
        pipeline_mod, "extract_quote_fields", lambda text: sample_extraction
    )
    client = TestClient(app)
    res = client.post(
        "/extract-quote",
        files={"file": ("scan.pdf", sparse_pdf, "application/pdf")},
    )
    assert res.status_code == 200
    assert res.json()["meta"]["extraction_engine"] == "docling"
