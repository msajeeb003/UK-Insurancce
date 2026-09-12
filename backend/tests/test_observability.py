"""Observability: PII/secret scrubbing, /readyz, client-error, metrics."""

from app.core import observability as obs

# ── Scrubbing ───────────────────────────────────────────────────────────────

def test_scrub_text_redacts_keys_and_tokens():
    assert "[redacted]" in obs.scrub_text("key is sk-proj-ABCDEFGH1234 ok")
    assert "[redacted]" in obs.scrub_text("Authorization: Bearer abc.def.ghi")


def test_scrub_data_redacts_sensitive_keys_and_drops_large_blobs():
    event = {
        "password": "hunter2",             # noqa: S106 — test data, not a real secret
        "api_key": "sk-live-XYZ",
        "buyer_note": "x" * 2000,          # long -> likely document text
        "nested": {"csrf_token": "t0ken", "ok": "fine"},  # noqa: S106
    }
    out = obs.scrub_data(event)
    assert out["password"] == "[redacted]"  # noqa: S105
    assert out["api_key"] == "[redacted]"
    assert out["buyer_note"].startswith("[omitted:")
    assert out["nested"]["csrf_token"] == "[redacted]"  # noqa: S105
    assert out["nested"]["ok"] == "fine"


def test_sentry_before_send_strips_request_body_and_headers():
    event = {"request": {"data": {"buyer": "ACME Ltd"},
                         "cookies": {"qct_session": "abc"},
                         "headers": {"Authorization": "Bearer x", "Accept": "json"}}}
    out = obs._sentry_before_send(event, {})
    assert "data" not in out["request"]
    assert "cookies" not in out["request"]
    assert out["request"]["headers"]["Authorization"] == "[redacted]"
    assert out["request"]["headers"]["Accept"] == "json"


# ── Health / readiness ──────────────────────────────────────────────────────

def test_healthz_is_shallow(anon_client):
    res = anon_client.get("/healthz")
    assert res.status_code == 200 and res.json()["status"] == "ok"


def test_readyz_ok_when_healthy(anon_client):
    res = anon_client.get("/readyz")
    assert res.status_code == 200
    assert res.json()["checks"]["db_writable"] is True
    assert res.json()["checks"]["data_dir_writable"] is True


def test_readyz_reflects_broken_dependency(anon_client, monkeypatch, tmp_path):
    # DATA_DIR under a regular file -> it cannot be created/written -> 503.
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "data_dir", str(blocker / "sub"))
    res = anon_client.get("/readyz")
    assert res.status_code == 503
    assert res.json()["status"] == "not-ready"
    assert res.json()["checks"]["data_dir_writable"] is not True


# ── Structured logging ──────────────────────────────────────────────────────

def test_response_carries_request_id_header(anon_client):
    res = anon_client.get("/healthz")
    assert res.headers.get("X-Request-Id")


def test_json_formatter_scrubs_and_adds_context():
    import json
    import logging

    from app.core.observability import JsonFormatter, request_id_var

    request_id_var.set("req-123")
    rec = logging.LogRecord("app", logging.INFO, __file__, 1,
                            "leak sk-proj-ABCDEFGH12345", (), None)
    rec.extra_fields = {"event": "extraction", "project_id": "p1", "duration_ms": 42}
    line = json.loads(JsonFormatter().format(rec))
    assert line["request_id"] == "req-123"
    assert line["event"] == "extraction" and line["project_id"] == "p1"
    assert "[redacted]" in line["msg"] and "sk-proj" not in line["msg"]


# ── Client error intake ─────────────────────────────────────────────────────

def test_client_error_accepts_and_scrubs(anon_client, caplog):
    res = anon_client.post("/client-error", json={
        "kind": "error", "message": "boom with sk-proj-SECRET12345", "where": "/review",
    })
    assert res.status_code == 200 and res.json()["ok"] is True


# ── Metrics ─────────────────────────────────────────────────────────────────

def test_metrics_requires_auth(anon_client):
    assert anon_client.get("/metrics").status_code == 401


def test_metrics_aggregates_success_measures(client):
    from app.api.observability import record_generation
    # two generations: 1 of 10 fields edited, then 2 of 10 -> 15% edit rate
    record_generation("m-proj-1", prep_seconds=120, generation_seconds=8.0,
                      fields_total=10, fields_edited=1)
    record_generation("m-proj-2", prep_seconds=240, generation_seconds=12.0,
                      fields_total=10, fields_edited=2)
    m = client.get("/metrics").json()
    assert m["generations"] >= 2
    assert m["exported_without_rebuild_pct"] == 100.0
    # edit rate and averages are present and numeric
    assert m["field_edit_rate_pct"] is not None
    assert m["avg_generation_seconds"] is not None
    assert m["avg_prep_minutes"] is not None
