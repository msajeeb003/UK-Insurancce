# ADR-0001: Persistence — SQLite now, Postgres when a trigger is hit

- **Status:** Accepted
- **Date:** 2026-09-12
- **Context owner:** platform / backend

## Context

The tool serves **3–4 internal users with identical permissions**, producing
roughly **20–30 projects/month**. It runs as a **single container** on Railway
with **gunicorn + several Uvicorn workers** against **one SQLite file** on a
persistent volume (`DATA_DIR/app.db`), backed up encrypted + offsite
(see [BACKUP.md](../BACKUP.md)).

Writes are small and short (one project blob, one row per document/export;
no long-held transactions). The database is configured for concurrent access:

- **WAL mode** (`PRAGMA journal_mode=WAL`) — readers never block the single
  writer, and vice versa.
- **`busy_timeout=5000`** — a second writer (another worker, or the
  `manage`/`backup` CLI) waits up to 5 s for the lock instead of erroring.
- **Foreign keys on**, writes serialised in-process by a lock and, across
  workers, by SQLite's own single-writer file lock.

This is verified by `backend/tests/test_concurrency.py` (six simultaneous
writers + a concurrent reader → no lost writes, no duplicates, no
corruption) and `test_app_connection_uses_wal_and_busy_timeout`.

At this scale SQLite is not a compromise — it removes an entire moving part
(no DB server to run, secure, patch or back up separately; a backup is one
file). The ceiling is **single-node write concurrency**, which the current
load is far below.

## Decision

**Stay on SQLite** until one of the triggers below is hit. Keep all data
access behind a single module (`app/core/db.py`) so a future swap is
localized, and keep schema changes flowing through the version-tracked
migration system (`MIGRATIONS` in `db.py`) so schema parity is reproducible.

## Triggers that force Postgres

Move when **any** of these becomes true — this is the deliberate line, not a
surprise:

1. **Write-lock contention under concurrent generation** — sustained
   `SQLITE_BUSY`, or write p95 latency climbing, when several users generate
   presentations / save at once. (The concurrency test is the canary; add
   metrics if this is suspected in production.)
2. **Concurrency growth** — more than ~8–10 active users, or gunicorn workers
   raised well beyond ~4 and writing heavily.
3. **Replicas / PITR** — a need for read replicas, or point-in-time recovery
   finer than the backup RPO (≤ 6 h). Postgres gives streaming replication +
   WAL-based PITR.
4. **Multi-instance / horizontal deploy** — running **more than one app
   container**. SQLite is single-node; a file on a shared network volume
   across instances is unsafe. **This is the hard trigger** — the day
   horizontal scaling is required, Postgres is mandatory.
5. **Dataset growth** — the DB or document set grows large enough that
   whole-file snapshots or single-node storage become impractical.

## Consequences of staying (accepted)

- Simple ops, one backup artefact, no DB server to secure/patch.
- Single-node write ceiling; recovery bounded by backup cadence (RPO ≤ 6 h).
- Horizontal scaling is blocked until the migration is done (trigger 4).

## Migration plan (execute only when a trigger fires)

The data-access layer is already localized: **every read/write goes through
`app/core/db.py`** (`execute` / `query` / `query_one` / `execute_transaction`),
and no SQL lives in the routes beyond parameterised strings. The swap is
therefore contained to that one module plus a data-copy script.

**1. Dependencies & config.** Add `psycopg[binary]`. Introduce
`DATABASE_URL` in settings: unset → SQLite (today); `postgresql://…` →
Postgres. `db._connect()` branches on it.

**2. Schema parity.** Reuse the existing `MIGRATIONS` list. The DDL is
almost identical; the known deltas to apply in the Postgres path:
   - `INTEGER PRIMARY KEY` (SQLite rowid) → `SERIAL`/`GENERATED … AS IDENTITY`.
   - Placeholders `?` → `%s` (centralise via a tiny param-style shim in
     `db.py`, or standardise on `%s` and translate for SQLite).
   - `INSERT … ON CONFLICT(col) DO UPDATE` — supported by both; keep as is.
   - `REAL` epoch timestamps → `double precision` (unchanged semantics).
   - `PRAGMA …` calls (WAL, busy_timeout, foreign_keys, integrity_check) are
     SQLite-only — guard them behind the SQLite branch; Postgres equivalents
     are server config, not per-connection.
   - `_schema_version` migration runner stays; wrap each migration in a real
     transaction (Postgres has transactional DDL).

**3. Data copy.** A one-off `python -m app.migrate_to_pg`: read every table
from SQLite and bulk-insert into Postgres **in FK order** —
`users → sessions → projects → documents → exports`. Uploaded documents and
generated exports are **files on the volume/offsite and do not move** — only
the metadata rows migrate.

**4. Cutover.** Announce a short maintenance window → stop the app (freeze
writes) → run the data copy → point `DATABASE_URL` at Postgres → deploy →
smoke-test (login, list projects, open a source page, generate). Backups
(`app/backup.py`) switch to `pg_dump`/PITR for the DB; the documents/exports
snapshot is unchanged.

**5. Rollback.** The copy is **non-destructive to SQLite** — the `app.db`
file is left intact. To roll back: unset `DATABASE_URL` and redeploy; the app
is back on SQLite with no data loss. Keep SQLite as the fallback until
Postgres has run cleanly for at least one full backup cycle.

## Acceptance (this ADR)

- ADR merged ✔
- WAL + busy_timeout confirmed and pinned by `test_concurrency.py` ✔
- Concurrency test (simultaneous saves + a generation, no corruption / no
  lost writes) in the suite ✔
- Migration plan written (above) ✔
