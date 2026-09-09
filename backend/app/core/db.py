"""
SQLite persistence (BRD 2.9/2.10): users, sessions, projects, retained
documents and generated exports.

One database file at <DATA_DIR>/app.db. SQLite fits the BRD's scale
(three to four internal users): no database server to run, and backing
up the deployment is copying the data directory. A single shared
connection is serialised with a lock; every statement commits.
"""

import sqlite3
import threading
import time
from pathlib import Path

from app.core.config import get_settings

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_conn_path: Path | None = None

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


def _connect() -> sqlite3.Connection:
    global _conn, _conn_path
    path = get_settings().data_path / "app.db"
    if _conn is None or _conn_path != path:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA)
        _conn, _conn_path = conn, path
    return _conn


def execute(sql: str, params: tuple = ()) -> None:
    with _lock:
        conn = _connect()
        conn.execute(sql, params)
        conn.commit()


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        return _connect().execute(sql, params).fetchall()


def query_one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def now() -> float:
    return time.time()
