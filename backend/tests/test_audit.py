"""Append-only audit trail (regulated-output traceability)."""

import sqlite3

import pytest

from app.core import audit, db
from tests.conftest import TEST_USER


def _latest(action: str) -> dict | None:
    rows = audit.recent(limit=5, action=action)
    return rows[0] if rows else None


def test_login_is_audited(client):
    # the `client` fixture logs in; a login entry should exist for the user
    row = _latest("login")
    assert row and row["actor"] == TEST_USER[0]


def test_project_save_and_delete_are_audited(client):
    state = {"id": "aud-1", "clientName": "Aldgate Timber Ltd",
             "confirmed": {"premium": True, "indemnity": False},
             "recommended": "col-a", "columns": [], "credit": [], "files": []}
    client.post("/projects", json={"id": "aud-1", "state": state})
    created = _latest("project.create")
    assert created["target"] == "aud-1" and created["actor"] == TEST_USER[0]
    assert "Aldgate Timber" in created["detail"] and "premium" in created["detail"]

    client.delete("/projects/aud-1")
    deleted = _latest("project.delete")
    assert deleted["target"] == "aud-1" and deleted["actor"] == TEST_USER[0]
    # the delete audit entry OUTLIVES the project it recorded
    assert db.query_one("SELECT 1 AS x FROM projects WHERE id='aud-1'") is None


def test_upload_and_export_are_audited(client, monkeypatch, sample_extraction, digital_pdf):
    from app.services import pipeline as pl
    monkeypatch.setattr(pl, "extract_quote_fields", lambda text: sample_extraction)

    client.post("/extract-quote",
                files={"file": ("q.pdf", digital_pdf, "application/pdf")},
                data={"project_id": "aud-2", "doc_kind": "quote"})
    up = _latest("document.upload")
    assert up["target"] and up["actor"] == TEST_USER[0]

    from tests.test_presentation import make_request
    payload = make_request().model_dump()
    client.post("/generate-presentation?format=pptx&project_id=aud-2", json=payload)
    exp = _latest("export")
    assert exp["actor"] == TEST_USER[0] and "pptx" in exp["detail"]
    client.delete("/projects/aud-2")


def test_audit_is_append_only(client):
    """UPDATE and DELETE on audit_log are blocked at the DB level."""
    audit.record("test.immutable", target="x", actor="tester")
    row = db.query_one("SELECT id FROM audit_log WHERE action='test.immutable'")
    with pytest.raises(sqlite3.Error):
        db.execute("UPDATE audit_log SET actor='forged' WHERE id=?", (row["id"],))
    with pytest.raises(sqlite3.Error):
        db.execute("DELETE FROM audit_log WHERE id=?", (row["id"],))
    still = db.query_one("SELECT actor FROM audit_log WHERE id=?", (row["id"],))
    assert still["actor"] == "tester"


def test_audit_view_and_export(client):
    assert client.get("/audit").status_code == 200
    assert client.get("/audit/view").status_code == 200
    res = client.get("/audit/export")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "timestamp_utc,actor,action,target,detail" in res.text.splitlines()[0]


def test_audit_requires_auth(anon_client):
    assert anon_client.get("/audit").status_code == 401
    assert anon_client.get("/audit/export").status_code == 401
