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


def test_rate_buckets_are_swept_of_idle_ips():
    """Idle IP buckets are removed (no unbounded memory growth), and the
    tracked-IP ceiling is enforced."""
    from collections import deque

    import app.main as m

    m._rate_buckets.clear()
    now = 1_000.0
    # 3 active IPs (recent) + 2 idle (last seen >60s ago)
    m._rate_buckets["active-1"] = deque([now - 5])
    m._rate_buckets["active-2"] = deque([now - 10])
    m._rate_buckets["active-3"] = deque([now - 59])
    m._rate_buckets["idle-1"] = deque([now - 120])
    m._rate_buckets["idle-2"] = deque([])          # emptied by an earlier prune
    try:
        m._sweep_rate_buckets(now)
        assert set(m._rate_buckets) == {"active-1", "active-2", "active-3"}
    finally:
        m._rate_buckets.clear()


def test_rate_buckets_respect_max_tracked_ips(monkeypatch):
    from collections import deque

    import app.main as m

    m._rate_buckets.clear()
    monkeypatch.setattr(m, "_MAX_TRACKED_IPS", 5)
    now = 1_000.0
    # 8 IPs, all recently active; only the 5 most-recent should survive.
    for i in range(8):
        m._rate_buckets[f"ip-{i}"] = deque([now - (8 - i)])  # ip-7 newest
    try:
        m._sweep_rate_buckets(now)
        assert len(m._rate_buckets) == 5
        assert "ip-7" in m._rate_buckets and "ip-0" not in m._rate_buckets
    finally:
        m._rate_buckets.clear()


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
