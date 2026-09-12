"""
Append-only audit trail of consequential actions (regulated-output
traceability). Metadata only — never document contents or buyer financials.

Records: actor, action, target, timestamp, and a small scrubbed detail blob.
The table's UPDATE/DELETE triggers make entries immutable (see migration v7),
and it is deliberately NOT touched by project deletion or retention purges —
the record that a project was deleted must outlive the project.
"""

import json
import logging

from app.core import db
from app.core.observability import scrub_data

logger = logging.getLogger("app.audit")


def record(action: str, target: str = "", actor: str = "system", **detail) -> None:
    """Append one audit entry. Best-effort: an audit failure must never break
    the user action, but it is logged loudly."""
    try:
        db.execute(
            "INSERT INTO audit_log (ts, actor, action, target, detail) "
            "VALUES (?,?,?,?,?)",
            (db.now(), actor or "system", action, target,
             json.dumps(scrub_data(detail), default=str)),
        )
    except Exception:
        logger.exception("Failed to write audit entry action=%s target=%s", action, target)


def recent(limit: int = 500, action: str = "") -> list[dict]:
    """Newest-first audit entries (admin view/export)."""
    if action:
        rows = db.query(
            "SELECT * FROM audit_log WHERE action=? ORDER BY id DESC LIMIT ?",
            (action, limit),
        )
    else:
        rows = db.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]
