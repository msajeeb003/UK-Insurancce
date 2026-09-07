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
    assert set(body) == {
        "status", "llm", "openai_configured", "anthropic_configured",
        "azure_configured",
    }


def test_insurers_endpoint_serves_configuration(client):
    res = client.get("/insurers")
    assert res.status_code == 200
    insurers = res.json()["insurers"]
    by_name = {i["name"]: i["debt_collection"] for i in insurers}
    # BRD 2.4 rule as configuration.
    assert by_name["Allianz Trade"] == "included"
    assert by_name["Atradius"] == "included"
    assert by_name["Coface"] == "included"
    assert by_name["QBE"] == "outsourced"


def test_security_headers(client):
    res = client.get("/health")
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"


def test_frontend_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Quote Comparison Tool" in res.text


def test_rejects_unsupported_type(client):
    res = client.post(
        "/extract-quote", files={"file": ("notes.txt", b"hello", "text/plain")}
    )
    assert res.status_code == 415


def test_legacy_xls_rejected_with_guidance(client):
    res = client.post(
        "/extract-quote",
        files={"file": ("limits.xls", b"\xd0\xcf\x11\xe0", "application/vnd.ms-excel")},
    )
    assert res.status_code == 415
    assert ".xlsx" in res.json()["detail"]


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


def test_no_provider_configured_is_503_without_leaking(client, digital_pdf, monkeypatch):
    from pydantic import SecretStr

    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "auto")
    monkeypatch.setattr(settings, "openai_api_key", SecretStr(""))
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr(""))
    res = client.post(
        "/extract-quote", files={"file": ("q.pdf", digital_pdf, "application/pdf")}
    )
    assert res.status_code == 503
    detail = res.json()["detail"]
    assert "OPENAI_API_KEY" in detail and "ANTHROPIC_API_KEY" in detail
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
    assert body["data"]["document_type"] == "insurer_quote"
    assert body["data"]["insurer"] == {
        "value": "ACME Credit Insurance plc", "page": 1, "confidence": "high",
    }
    # The sanitizer must have cleared the hallucinated page citation.
    assert body["data"]["indemnity"] == {
        "value": "90%", "page": None, "confidence": "high",
    }
    # The review summary flags what a broker must check (BRD 2.5).
    assert "minimum_annual_premium" in body["review"]["missing_fields"]
    # The verification pass catches the fixture's fabricated values (they
    # don't appear in the PDF text) and downgrades them.
    assert set(body["review"]["unverified_fields"]) == {
        "excess", "excess_type", "discretionary_limit",
    }
    assert set(body["review"]["uncertain_fields"]) == {
        "excess", "excess_type", "discretionary_limit",
    }
    assert body["data"]["excess"]["confidence"] == "uncertain"
    # Values genuinely present in the PDF stay verified and 'high'.
    assert body["data"]["annual_turnover"]["confidence"] == "high"
    assert body["review"]["confirm_required"] == [
        "estimated_annual_premium_exc_ipt", "indemnity", "excess",
        "max_annual_liability",
    ]
    # BRD 2.4: debt collection is rule-set, never extracted; unknown insurer
    # defaults to Outsourced.
    assert body["set_fields"]["debt_collection_support"] == {
        "value": "Outsourced", "source": "insurer_rule", "matched_insurer": None,
    }
    # Set fields must not exist inside the extraction itself.
    assert "type_of_policy" not in body["data"]
    assert "debt_collection_support" not in body["data"]


def test_excel_schedule_accepted(client, limits_xlsx, sample_extraction, monkeypatch):
    sample_extraction.document_type = "credit_limit_schedule"
    sample_extraction.insurer.value = "Atradius"
    monkeypatch.setattr(
        pipeline_mod, "extract_quote_fields", lambda text: sample_extraction
    )
    res = client.post(
        "/extract-quote",
        files={"file": (
            "limits.xlsx", limits_xlsx,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["meta"]["extraction_engine"] == "excel"
    assert body["meta"]["page_count"] == 1  # one worksheet
    assert body["data"]["document_type"] == "credit_limit_schedule"
    # Atradius is on the standing list -> rule says Included.
    assert body["set_fields"]["debt_collection_support"] == {
        "value": "Included", "source": "insurer_rule", "matched_insurer": "Atradius",
    }


def test_unexpected_error_is_opaque_502(client, digital_pdf, monkeypatch):
    def boom(text):
        raise RuntimeError("internal secret: /etc/passwd")
    monkeypatch.setattr(pipeline_mod, "extract_quote_fields", boom)
    res = client.post(
        "/extract-quote", files={"file": ("q.pdf", digital_pdf, "application/pdf")}
    )
    assert res.status_code == 502
    assert "internal secret" not in res.text
