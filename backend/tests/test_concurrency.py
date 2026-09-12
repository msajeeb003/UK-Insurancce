"""Concurrency safety of the SQLite write path (ADR-0001).

Confirms the app's connection uses WAL + busy_timeout, and that several
simultaneous writers plus a concurrent reader (mirroring several gunicorn
workers saving projects while one generates a presentation) produce no lost
writes and no corruption. Each thread uses its OWN connection, the way each
worker process has its own — so this exercises SQLite's cross-connection
file locking, WAL and busy_timeout, not the in-process lock.
"""

import sqlite3
import threading


def test_app_connection_uses_wal_and_busy_timeout():
    from app.core import db

    conn = db._connect()
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def _connect(path):
    c = sqlite3.connect(path, timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    return c


def test_concurrent_writers_no_lost_writes_no_corruption(tmp_path):
    db_path = tmp_path / "concurrent.db"
    init = _connect(db_path)
    init.execute("CREATE TABLE writes (worker INTEGER, seq INTEGER)")
    init.commit()
    init.close()

    n_workers, per_worker = 6, 50
    errors: list[Exception] = []

    def writer(w: int) -> None:
        try:
            c = _connect(db_path)
            for i in range(per_worker):
                c.execute("INSERT INTO writes VALUES (?, ?)", (w, i))
                c.commit()
            c.close()
        except Exception as exc:               # SQLITE_BUSY etc. would land here
            errors.append(exc)

    def reader() -> None:                        # a "generation" reading during writes
        try:
            c = _connect(db_path)
            for _ in range(per_worker):
                c.execute("SELECT COUNT(*) FROM writes").fetchone()
            c.close()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(w,)) for w in range(n_workers)]
    threads.append(threading.Thread(target=reader))
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent access raised: {errors}"

    check = _connect(db_path)
    total = check.execute("SELECT COUNT(*) FROM writes").fetchone()[0]
    distinct = check.execute("SELECT COUNT(DISTINCT worker || '-' || seq) FROM writes").fetchone()[0]
    integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
    check.close()

    assert total == n_workers * per_worker       # no lost writes
    assert distinct == n_workers * per_worker    # no duplicates/overwrites
    assert integrity == "ok"                     # no corruption
