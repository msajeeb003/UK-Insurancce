"""
Scheduled data retention (BRD 2.11): hard-delete projects untouched for
longer than RETENTION_DAYS. Reuses the atomic per-project erase, so a purge
leaves nothing orphaned (DB rows and files both go). Disabled when
RETENTION_DAYS = 0 (the retention period is the client's decision).

CLI:  python -m app.retention run     # purge now
      python -m app.retention due     # list what would be purged (dry run)
"""

import logging
import sys
import time

from app.api.projects import delete_project_data
from app.core import db
from app.core.config import get_settings

logger = logging.getLogger("app.retention")


def expired_project_ids() -> list[str]:
    """Projects whose last activity is older than the retention window.
    Empty when retention is disabled (RETENTION_DAYS = 0)."""
    days = get_settings().retention_days
    if days <= 0:
        return []
    cutoff = time.time() - days * 86400
    rows = db.query(
        "SELECT id FROM projects WHERE updated < ? ORDER BY updated", (cutoff,)
    )
    return [r["id"] for r in rows]


def purge_expired() -> list[str]:
    """Delete every expired project (atomic per project). Returns the ids
    purged. Idempotent and safe to run concurrently."""
    ids = expired_project_ids()
    for project_id in ids:
        delete_project_data(project_id)
        logger.info("Retention purge removed project", extra={
            "extra_fields": {"event": "retention_purge", "project_id": project_id}})
    if ids:
        logger.info("Retention purge complete", extra={
            "extra_fields": {"event": "retention_purge_done", "count": len(ids)}})
    return ids


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = argv if argv is not None else sys.argv[1:]
    cmd = args[0] if args else ""
    days = get_settings().retention_days
    if cmd == "due":
        ids = expired_project_ids()
        print(f"retention_days={days}; {len(ids)} project(s) due for purge")
        for i in ids:
            print(i)
        return 0
    if cmd == "run":
        if days <= 0:
            print("Retention disabled (RETENTION_DAYS=0) — nothing purged.")
            return 0
        purged = purge_expired()
        print(f"Purged {len(purged)} project(s) older than {days} days.")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
