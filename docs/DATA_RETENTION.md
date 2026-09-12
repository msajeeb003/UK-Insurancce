# Data retention & erasure statement

Confidential data (client financials, named buyers, insurer quotes) is held
only as long as needed and can be erased on request. The **retention period is
the client's decision** — set `RETENTION_DAYS`; until then nothing is
auto-deleted.

## What is held, and for how long

| Data | Where | Retention |
|---|---|---|
| Projects (reviewed comparison state) | SQLite `projects` | until purged (`RETENTION_DAYS` after last activity) or deleted on request |
| Uploaded documents (quotes, schedules, expiring policy) | `DATA_DIR/projects/<id>/docs` | same as the project |
| Generated exports (PPTX/PDF/XLSX) | `DATA_DIR/projects/<id>/exports` | same as the project |
| Per-generation metrics (timings, counts — no buyer data) | SQLite `metrics` | same as the project |
| Users | SQLite `users` | until removed via the manage CLI |
| Sessions | SQLite `sessions` | `SESSION_TTL_HOURS` (default 72h), swept hourly |
| Backups (encrypted, offsite) | S3/bucket or offsite dir | `BACKUP_RETENTION_DAILY` (30) + `BACKUP_RETENTION_MONTHLY` (12) |

## Scheduled deletion (retention window)

- `RETENTION_DAYS` (default **0 = disabled**). When set > 0, a **daily purge**
  hard-deletes every project whose **last activity** (`updated`) is older than
  the window.
- Each purge reuses the atomic per-project erase: the `projects`, `documents`,
  `exports` and `metrics` rows are deleted in **one transaction**, then the
  project's files are removed — so nothing is left orphaned.
- Runs in-process daily, and can also be run explicitly:
  ```bash
  python -m app.retention due    # dry run — list what would be purged
  python -m app.retention run    # purge now
  ```
  (Wire `run` into a Railway cron if you prefer an external schedule.)

## Right to erasure (on request)

An admin deletes a specific client/project immediately:
```
DELETE /projects/<project-id>      # authenticated + CSRF
```
This removes all DB rows (project, documents, exports, metrics) **and** the
project's files from live storage.

**Backup lag (documented):** point-in-time backups taken *before* the deletion
still contain the project until they age out of the backup retention window
(up to ~12 months for the monthly copies). This is expected for any
backup-based system. If a hard "erase from backups too, now" is required for a
specific request, rotate/delete the affected offsite backup objects manually
and note it in the erasure record; otherwise the data disappears naturally as
those backups expire.

## Verify

- Set `RETENTION_DAYS=30`, then `python -m app.retention due` lists projects
  untouched for 30+ days; `run` removes them (rows + files, nothing orphaned).
- `DELETE /projects/<id>` removes every trace from live storage immediately.
- Covered by `backend/tests/test_retention.py`.
