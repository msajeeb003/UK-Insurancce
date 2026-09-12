"""SQLite persistence (BRD 2.9/2.10): users, sessions, projects, documents,
exports. One file at <DATA_DIR>/app.db — fits the BRD's 3-4 user scale.

Writes are serialised through one locked connection (SQLite allows a single
writer, so the lock avoids "database is locked" rather than causing it);
busy_timeout covers a second process (the manage CLI) touching the file.
"""

import logging
import sqlite3
import threading
import time
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_conn_path: Path | None = None

# The version-1 schema. Every statement uses IF NOT EXISTS, so applying it
# to a fresh OR an already-created database is safe (idempotent).
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    client_name TEXT NOT NULL DEFAULT '',
    updated REAL NOT NULL,
    state TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'quote',
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    page_count INTEGER NOT NULL DEFAULT 0,
    uploaded REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS exports (
    project_id TEXT NOT NULL,
    format TEXT NOT NULL,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    created REAL NOT NULL,
    PRIMARY KEY (project_id, format)
);
"""

# ── Schema migrations (lightweight, no Alembic) ──────────────────────────
# Each entry is (version, sql_script), applied in ascending order exactly
# once. `_schema_version` records which have run, so `CREATE TABLE IF NOT
# EXISTS` on its own — which does nothing to an existing table — is no
# longer the only tool: to change the schema you append a NEW migration.
#
# RULES for adding one:
#   * Append only; never edit or reorder an existing entry — deployed
#     databases have already applied it and are tracking by version number.
#   * Give it the next integer version.
#   * Write it to be safe to re-run where you can (IF NOT EXISTS, etc.).
#
# Version 1 is the base schema above. Version 2 is an EXAMPLE showing how a
# future column is added — `owner_id` is not used yet (BRD 2.10: all users
# see all projects), it is here purely to demonstrate the pattern.
MIGRATIONS: list[tuple[int, str]] = [
    (1, SCHEMA),
    (2, "ALTER TABLE projects ADD COLUMN owner_id TEXT NOT NULL DEFAULT ''"),
    # v3: per-session CSRF token. Existing sessions get '' and so fail the
    # CSRF check on their next state-changing request — the broker simply
    # signs in again and gets a fresh token.
    (3, "ALTER TABLE sessions ADD COLUMN csrf_token TEXT NOT NULL DEFAULT ''"),
    # v4: per-generation metrics for the BRD success measures.
    (4, """
    CREATE TABLE IF NOT EXISTS metrics (
        id INTEGER PRIMARY KEY,
        project_id TEXT NOT NULL,
        created REAL NOT NULL,
        prep_seconds REAL,
        generation_seconds REAL,
        fields_total INTEGER NOT NULL DEFAULT 0,
        fields_edited INTEGER NOT NULL DEFAULT 0,
        exported INTEGER NOT NULL DEFAULT 0
    );
    """),
    # v5: login throttle / lockout (keyed by 'acct:<email>' and 'ip:<addr>').
    (5, """
    CREATE TABLE IF NOT EXISTS login_throttle (
        key TEXT PRIMARY KEY,
        failed INTEGER NOT NULL DEFAULT 0,
        locked_until REAL NOT NULL DEFAULT 0,
        updated REAL NOT NULL
    );
    """),
    # v6: session inactivity tracking (0 = grandfathered / not yet seen).
    (6, "ALTER TABLE sessions ADD COLUMN last_seen REAL NOT NULL DEFAULT 0"),
    # v7: append-only audit trail. Triggers block UPDATE/DELETE at the DB
    # level, so entries are immutable even against the app or a manual client.
    (7, """
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY,
        ts REAL NOT NULL,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        target TEXT NOT NULL DEFAULT '',
        detail TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TRIGGER IF NOT EXISTS audit_log_no_update
        BEFORE UPDATE ON audit_log
        BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
    CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
        BEFORE DELETE ON audit_log
        BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
    """),
]


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Bring the database up to the latest schema version.

    Reads the highest applied version from `_schema_version`, then applies
    every migration newer than that, in order. Each migration and the row
    that records its version are committed together in ONE transaction
    (SQLite can roll back DDL), so a crash mid-migration leaves the schema
    untouched and the migration simply retries on the next startup —
    never half-applied.
    """
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS _schema_version ("
        "  version INTEGER PRIMARY KEY,"
        "  applied REAL NOT NULL"
        ");"
    )
    row = conn.execute("SELECT MAX(version) AS v FROM _schema_version").fetchone()
    current = row["v"] or 0
    for version, sql in MIGRATIONS:
        if version <= current:
            continue
        # version/timestamp are trusted internal numerics (not user input),
        # so embedding them keeps the whole step inside one executescript
        # transaction — the only way to apply DDL and record the version
        # atomically (executescript ignores isolation_level).
        # version/time are internal numerics (not user input), so embedding
        # them is safe and keeps migration + version-bump in one transaction.
        record = f"INSERT INTO _schema_version (version, applied) VALUES ({version}, {time.time()});"  # noqa: S608
        conn.executescript(
            "BEGIN;\n" + sql.rstrip().rstrip(";") + ";\n" + record + "\nCOMMIT;"
        )
        logger.info("Applied schema migration v%s", version)


def _connect() -> sqlite3.Connection:
    global _conn, _conn_path
    path = get_settings().data_path / "app.db"
    if _conn is None or _conn_path != path:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        # Wait up to 5s for another process (e.g. the manage.py CLI) to
        # release the write lock instead of failing immediately with
        # SQLITE_BUSY.
        conn.execute("PRAGMA busy_timeout=5000")
        _run_migrations(conn)
        _conn, _conn_path = conn, path
    return _conn


def execute(sql: str, params: tuple = ()) -> None:
    with _lock:
        conn = _connect()
        conn.execute(sql, params)
        conn.commit()


def execute_transaction(statements: list[tuple[str, tuple]]) -> None:
    """Run several writes as ONE atomic transaction — either all of them
    commit, or none do. Use it wherever a single logical change spans more
    than one statement (e.g. deleting a project together with its
    documents and exports, BRD 2.11): a crash midway can no longer leave
    the database half-updated. Python's sqlite3 opens a transaction before
    the first write and holds it until commit(), so the whole list lands
    atomically; any error rolls the batch back."""
    with _lock:
        conn = _connect()
        try:
            for sql, params in statements:
                conn.execute(sql, params)
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        return _connect().execute(sql, params).fetchall()


def query_one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def now() -> float:
    return time.time()
