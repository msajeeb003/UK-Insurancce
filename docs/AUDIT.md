# Audit trail

An append-only record of consequential actions, for regulated-output
traceability.

## ⚠ Scope note — deviates from BRD 2.9

BRD v1.2 §2.9 explicitly states **"no audit trail in this build."** This
feature is a **deliberate production upgrade** beyond that scope. **Confirm
with the client before treating it as an operational control** — some clients
prefer the minimal footprint the BRD described, others require an audit trail
for regulated advice. It is implemented and available; enabling it as a
compliance control is a client decision.

## What is recorded

Metadata only — **never document contents or buyer financials**:

| Action | When | Target |
|---|---|---|
| `login` | successful sign-in | account email |
| `project.create` / `project.save` | project saved (includes confirmed key values + recommendation from the saved state) | project id |
| `document.upload` | a document is extracted into a project | document id |
| `export` | a presentation/PDF/Excel is generated | project id |
| `project.delete` | on-request erasure | project id |
| `config.reload` | insurers/terminology config changes on disk | filename |
| `audit.export` | the audit log is exported | — |

Each entry stores **actor, action, target, timestamp**, and a small scrubbed
detail blob. Field confirmations and recommendation selection are captured
from the saved project state (`project.save`) and again at `export` — the
regulated output point.

## Append-only

`audit_log` has DB triggers that **block UPDATE and DELETE** (migration v7),
so entries are immutable even against the application or a manual SQLite
client. Nothing in the app ever edits or deletes an entry. The trail is
**deliberately excluded** from project deletion and retention purges — the
record that a project was deleted must outlive the project. (Entries are
metadata only, so retaining them after erasure is consistent with data
minimisation.)

## Admin view / export

Authenticated endpoints:

- `GET /audit` — JSON (newest first; `?limit=`, `?action=`).
- `GET /audit/view` — a minimal HTML table.
- `GET /audit/export` — full trail as CSV (the export is itself audited).

## Verify

- Sign in, save a project, upload a document, generate a deck, delete a
  project → each appears in `/audit/view` with the correct actor and target.
- An UPDATE/DELETE against `audit_log` raises (append-only).
- Covered by `backend/tests/test_audit.py`.
