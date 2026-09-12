"""Data retention purge + right-to-erasure (BRD 2.11)."""

import time

from app import retention
from app.api.projects import delete_project_data
from app.core import db
from app.core.config import get_settings


def _seed_project(pid: str, updated: float) -> None:
    """A project row + a document row + a metrics row + a file on disk."""
    db.execute("INSERT INTO projects (id, client_name, updated, state) VALUES (?,?,?,?)",
               (pid, "Acme Ltd", updated, "{}"))
    db.execute("INSERT INTO documents (id, project_id, kind, filename, stored_path, "
               "page_count, uploaded) VALUES (?,?,?,?,?,?,?)",
               (pid + "-d", pid, "quote", "q.pdf", "/x", 1, updated))
    db.execute("INSERT INTO metrics (project_id, created, generation_seconds, "
               "fields_total, fields_edited, exported) VALUES (?,?,?,?,?,1)",
               (pid, updated, 5.0, 10, 1))
    folder = get_settings().data_path / "projects" / pid / "docs"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "q.pdf").write_bytes(b"%PDF-1.4 doc")


def _exists(pid: str) -> dict:
    return {
        "project": db.query_one("SELECT 1 AS x FROM projects WHERE id=?", (pid,)) is not None,
        "document": db.query_one("SELECT 1 AS x FROM documents WHERE project_id=?", (pid,)) is not None,
        "metric": db.query_one("SELECT 1 AS x FROM metrics WHERE project_id=?", (pid,)) is not None,
        "folder": (get_settings().data_path / "projects" / pid).exists(),
    }


def test_on_request_delete_removes_all_traces(client):
    _seed_project("erase-1", time.time())
    assert all(_exists("erase-1").values())
    delete_project_data("erase-1")
    assert not any(_exists("erase-1").values())     # no dangling rows or files


def test_retention_purges_expired_keeps_recent(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "retention_days", 30)
    now = time.time()
    _seed_project("old-1", now - 40 * 86400)        # 40 days old -> expired
    _seed_project("new-1", now - 5 * 86400)         # 5 days old -> kept

    purged = retention.purge_expired()
    assert "old-1" in purged and "new-1" not in purged
    assert not any(_exists("old-1").values())        # fully removed, no orphans
    assert all(_exists("new-1").values())            # untouched
    delete_project_data("new-1")                     # cleanup


def test_retention_disabled_when_zero(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "retention_days", 0)
    _seed_project("keep-forever", time.time() - 9999 * 86400)
    assert retention.expired_project_ids() == []
    assert retention.purge_expired() == []
    assert all(_exists("keep-forever").values())
    delete_project_data("keep-forever")              # cleanup
