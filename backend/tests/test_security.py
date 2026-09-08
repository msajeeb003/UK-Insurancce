"""Hardening: rate limiting, payload caps, header safety, CSP."""

import app.main as main_mod
from app.core.config import get_settings
from tests.test_presentation import make_request


def test_rate_limit_kicks_in(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_per_minute", 3)
    main_mod._rate_buckets.clear()
    try:
        statuses = []
        for _ in range(4):
            res = client.post(
                "/extract-quote",
                files={"file": ("x.pdf", b"not a pdf", "application/pdf")},
            )
            statuses.append(res.status_code)
        assert statuses[:3] == [422, 422, 422]  # rejected, but counted
        assert statuses[3] == 429
        assert "Rate limit" in res.json()["detail"]
    finally:
        main_mod._rate_buckets.clear()


def test_rate_limit_skips_read_endpoints(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_per_minute", 1)
    main_mod._rate_buckets.clear()
    try:
        for _ in range(5):
            assert client.get("/health").status_code == 200
    finally:
        main_mod._rate_buckets.clear()


def test_csp_header_present(client):
    res = client.get("/")
    csp = res.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_presentation_payload_caps(client):
    payload = make_request().model_dump()
    payload["columns"][0]["values"] = {f"k{i}": "v" for i in range(50)}
    res = client.post("/generate-presentation?format=pptx", json=payload)
    assert res.status_code == 422  # too many value entries


def test_non_ascii_client_name_cannot_break_download(client):
    payload = make_request(client_name="আলডগেট টিম্বার লিমিটেড ✨").model_dump()
    res = client.post("/generate-presentation?format=pptx", json=payload)
    assert res.status_code == 200
    disposition = res.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    # Header value must be pure ASCII (latin-1-safe).
    disposition.encode("ascii")
