"""Authentication + server-side project storage (BRD 2.9/2.10/S1/S2)."""

from tests.conftest import TEST_USER
from tests.test_presentation import make_request


def test_data_endpoints_require_sign_in(anon_client):
    assert anon_client.get("/projects").status_code == 401
    assert anon_client.post("/extract-quote").status_code == 401
    assert anon_client.post(
        "/generate-presentation", json=make_request().model_dump()
    ).status_code == 401
    # Liveness stays open for the reverse proxy / monitoring.
    assert anon_client.get("/health").status_code == 200


def test_wrong_password_rejected(anon_client):
    res = anon_client.post(
        "/auth/login", json={"email": TEST_USER[0], "password": "wrong"}
    )
    assert res.status_code == 401


def test_csrf_required_on_writes(client):
    """A logged-in write without the X-CSRF-Token header is rejected (403);
    with the correct token it succeeds. Login itself is exempt."""
    from tests.test_presentation import make_request

    payload = make_request().model_dump()
    good = client.headers["X-CSRF-Token"]

    # Missing header -> 403
    res = client.post("/generate-presentation?format=pptx", json=payload,
                      headers={"X-CSRF-Token": ""})
    assert res.status_code == 403
    # Wrong header -> 403
    res = client.post("/generate-presentation?format=pptx", json=payload,
                      headers={"X-CSRF-Token": "not-the-real-token"})
    assert res.status_code == 403
    # Correct header (the fixture's default) -> allowed
    res = client.post("/generate-presentation?format=pptx", json=payload)
    assert res.status_code == 200
    assert good  # sanity: a real token was issued


def test_login_returns_csrf_token(anon_client):
    from app.core import auth, db
    from tests.conftest import TEST_USER
    if not db.query_one("SELECT id FROM users WHERE email=?", (TEST_USER[0],)):
        auth.create_user(*TEST_USER)
    res = anon_client.post("/auth/login",
                           json={"email": TEST_USER[0], "password": TEST_USER[1]})
    assert res.status_code == 200
    assert len(res.json()["csrf_token"]) > 20      # a real random token


def test_login_me_logout_roundtrip(client):
    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == TEST_USER[0]
    assert client.post("/auth/logout").status_code == 200
    assert client.get("/auth/me").status_code == 401


def test_project_save_list_delete(client):
    state = {"id": "p-test-1", "clientName": "Aldgate Timber Ltd",
             "columns": [], "credit": [], "files": []}
    assert client.post(
        "/projects", json={"id": "p-test-1", "state": state}
    ).status_code == 200

    listed = client.get("/projects").json()["projects"]
    mine = next(p for p in listed if p["id"] == "p-test-1")
    assert mine["clientName"] == "Aldgate Timber Ltd"

    # Reopen = the same reviewed state comes back verbatim (BRD S2).
    state["clientName"] = "Renamed Ltd"
    client.post("/projects", json={"id": "p-test-1", "state": state})
    listed = client.get("/projects").json()["projects"]
    assert next(p for p in listed if p["id"] == "p-test-1")["clientName"] == "Renamed Ltd"

    assert client.delete("/projects/p-test-1").status_code == 200
    listed = client.get("/projects").json()["projects"]
    assert not any(p["id"] == "p-test-1" for p in listed)


def test_migrations_apply_and_are_idempotent(tmp_path):
    """A fresh database is brought to the latest version, the example
    migration's column exists, and re-running does nothing (no error)."""
    import sqlite3

    from app.core import db

    conn = sqlite3.connect(tmp_path / "fresh.db")
    conn.row_factory = sqlite3.Row
    db._run_migrations(conn)

    latest = db.MIGRATIONS[-1][0]
    v = conn.execute("SELECT MAX(version) AS v FROM _schema_version").fetchone()["v"]
    assert v == latest
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(projects)")]
    assert "owner_id" in cols                      # v2 example migration ran

    db._run_migrations(conn)                        # re-run: no-op, no error
    v2 = conn.execute("SELECT MAX(version) AS v FROM _schema_version").fetchone()["v"]
    assert v2 == latest
    conn.close()


def test_migration_upgrades_an_old_database(tmp_path):
    """A database created the old way (base tables, no _schema_version)
    upgrades cleanly — the new column is added without touching data."""
    import sqlite3

    from app.core import db

    conn = sqlite3.connect(tmp_path / "old.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(db.SCHEMA)                   # old-style: base tables only
    conn.execute("INSERT INTO projects (id, client_name, updated, state) "
                 "VALUES ('keep-me', 'Acme', 1.0, '{}')")
    conn.commit()

    db._run_migrations(conn)

    cols = [r["name"] for r in conn.execute("PRAGMA table_info(projects)")]
    assert "owner_id" in cols
    # existing data survives the migration
    row = conn.execute("SELECT client_name, owner_id FROM projects WHERE id='keep-me'").fetchone()
    assert row["client_name"] == "Acme" and row["owner_id"] == ""
    conn.close()


def test_expired_session_rejected_but_not_deleted_on_check(client):
    """An auth check rejects an expired session via the query filter and no
    longer runs a DELETE — cleanup is a separate background job."""
    from app.core import auth, db

    if not db.query_one("SELECT id FROM users WHERE email=?", ("exp@test.local",)):
        auth.create_user("exp@test.local", "pw-12345678")
    uid = db.query_one("SELECT id FROM users WHERE email=?", ("exp@test.local",))["id"]
    token = "raw-expired-token"  # noqa: S105 — test fixture, not a real secret
    th = auth._token_hash(token)
    db.execute("INSERT INTO sessions (token_hash, user_id, expires) VALUES (?,?,?)",
               (th, uid, db.now() - 10))          # already expired

    assert auth.user_for_token(token) is None      # rejected
    # the check did NOT delete it (no per-request cleanup)
    assert db.query_one("SELECT 1 AS x FROM sessions WHERE token_hash=?", (th,)) is not None

    auth.delete_expired_sessions()                 # background job clears it
    assert db.query_one("SELECT 1 AS x FROM sessions WHERE token_hash=?", (th,)) is None
    db.execute("DELETE FROM users WHERE email=?", ("exp@test.local",))


def test_delete_expired_sessions_keeps_valid_ones(client):
    from app.core import auth, db

    if not db.query_one("SELECT id FROM users WHERE email=?", ("v@test.local",)):
        auth.create_user("v@test.local", "pw-12345678")
    uid = db.query_one("SELECT id FROM users WHERE email=?", ("v@test.local",))["id"]
    db.execute("INSERT INTO sessions (token_hash, user_id, expires) VALUES (?,?,?)",
               ("valid-tok", uid, db.now() + 3600))
    db.execute("INSERT INTO sessions (token_hash, user_id, expires) VALUES (?,?,?)",
               ("expired-tok", uid, db.now() - 1))

    auth.delete_expired_sessions()
    assert db.query_one("SELECT 1 AS x FROM sessions WHERE token_hash='valid-tok'") is not None
    assert db.query_one("SELECT 1 AS x FROM sessions WHERE token_hash='expired-tok'") is None
    db.execute("DELETE FROM users WHERE email=?", ("v@test.local",))


def test_execute_transaction_is_atomic(client):
    """A multi-statement write rolls back entirely if any statement fails —
    a project deletion (BRD 2.11) can never land half-applied."""
    import sqlite3

    import pytest

    from app.core import db

    db.execute(
        "INSERT INTO projects (id, client_name, updated, state) VALUES (?,?,?,?)",
        ("tx-1", "Original", db.now(), "{}"),
    )
    with pytest.raises(sqlite3.Error):
        db.execute_transaction([
            ("UPDATE projects SET client_name='Changed' WHERE id=?", ("tx-1",)),
            ("DELETE FROM no_such_table WHERE x=?", (1,)),  # fails -> rollback
        ])
    row = db.query_one("SELECT client_name FROM projects WHERE id=?", ("tx-1",))
    assert row["client_name"] == "Original"   # first UPDATE was rolled back
    db.execute("DELETE FROM projects WHERE id=?", ("tx-1",))


def test_delete_removes_documents_and_exports(client):
    """delete_project clears the project, its documents and its exports."""
    from app.core import db

    db.execute("INSERT INTO projects (id, client_name, updated, state) VALUES (?,?,?,?)",
               ("del-1", "X", db.now(), "{}"))
    db.execute("INSERT INTO documents (id, project_id, kind, filename, stored_path, "
               "page_count, uploaded) VALUES (?,?,?,?,?,?,?)",
               ("doc-1", "del-1", "quote", "q.pdf", "/x", 1, db.now()))
    db.execute("INSERT INTO exports (project_id, format, filename, stored_path, created) "
               "VALUES (?,?,?,?,?)", ("del-1", "pdf", "d.pdf", "/x", db.now()))

    assert client.delete("/projects/del-1").status_code == 200
    assert db.query_one("SELECT id FROM projects WHERE id=?", ("del-1",)) is None
    assert db.query_one("SELECT id FROM documents WHERE project_id=?", ("del-1",)) is None
    assert db.query_one("SELECT format FROM exports WHERE project_id=?", ("del-1",)) is None


def test_export_is_retained_and_downloadable(client):
    payload = make_request().model_dump()
    res = client.post(
        "/generate-presentation?format=pptx&project_id=p-exp-1", json=payload
    )
    assert res.status_code == 200

    stored = client.get("/projects/p-exp-1/exports/pptx")
    assert stored.status_code == 200
    assert stored.content == res.content
    assert "Aldgate Timber Ltd" in stored.headers["content-disposition"]

    assert client.get("/projects/p-exp-1/exports/pdf").status_code == 404
    client.delete("/projects/p-exp-1")


def test_document_retained_with_source_page_view(client, digital_pdf,
                                                 sample_extraction, monkeypatch):
    from app.services import pipeline as pl

    monkeypatch.setattr(pl, "extract_quote_fields", lambda text: sample_extraction)

    res = client.post(
        "/extract-quote",
        files={"file": ("quote.pdf", digital_pdf, "application/pdf")},
        data={"project_id": "p-doc-1", "doc_kind": "quote"},
    )
    assert res.status_code == 200
    doc_id = res.json()["meta"]["document_id"]
    assert doc_id

    # S5: clicking a value opens the source PDF page.
    page = client.get(f"/documents/{doc_id}/page/1")
    assert page.status_code == 200
    assert page.headers["content-type"] == "image/png"
    assert page.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get(f"/documents/{doc_id}/page/99").status_code == 404
    client.delete("/projects/p-doc-1")
