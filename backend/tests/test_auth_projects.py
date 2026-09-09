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
