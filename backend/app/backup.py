"""
Encrypted, offsite backups for the DATA_DIR (SQLite DB + documents + exports).

One backup = a consistent SQLite snapshot (via the online backup API, never
a copy of the live file) plus the projects/ tree, tarred, Fernet-encrypted,
and pushed to an offsite store (S3-compatible bucket, or a directory / second
volume). Old backups are pruned to a daily+monthly retention window.

CLI:
    python -m app.backup gen-key           # print a new encryption key
    python -m app.backup run               # snapshot -> encrypt -> upload -> prune
    python -m app.backup run --if-configured   # no-op when backups aren't set up
    python -m app.backup list              # list offsite backups
    python -m app.backup integrity         # PRAGMA integrity_check on the live DB
    python -m app.backup restore <name> [--target DIR]   # restore a backup

Scheduling and the restore runbook live in docs/BACKUP.md.
"""

import io
import json
import logging
import sqlite3
import sys
import tarfile
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger("app.backup")

_PREFIX = "backup-"
_SUFFIX = ".tar.gz.enc"


# ── Encryption ────────────────────────────────────────────────────────────

def _fernet():
    from cryptography.fernet import Fernet  # lazy: only needed for backups

    key = get_settings().backup_encryption_key.get_secret_value()
    if not key:
        raise RuntimeError(
            "BACKUP_ENCRYPTION_KEY is not set — run `python -m app.backup gen-key`."
        )
    return Fernet(key.encode())


# ── Offsite stores (S3-compatible, or a directory) ─────────────────────────

class _DirStore:
    """Offsite = a directory (a second mounted volume, or local for tests)."""

    def __init__(self, path: str):
        self.dir = Path(path)
        self.dir.mkdir(parents=True, exist_ok=True)

    def put(self, name: str, data: bytes) -> None:
        (self.dir / name).write_bytes(data)

    def get(self, name: str) -> bytes:
        return (self.dir / name).read_bytes()

    def list(self) -> list[str]:
        return sorted(p.name for p in self.dir.glob(f"{_PREFIX}*{_SUFFIX}"))

    def delete(self, name: str) -> None:
        (self.dir / name).unlink(missing_ok=True)


class _S3Store:
    """Offsite = an S3-compatible bucket (AWS EU, Cloudflare R2, Backblaze B2…)."""

    def __init__(self, s):
        import boto3  # lazy: only needed when an S3 bucket is configured

        self.bucket = s.backup_s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=s.backup_s3_endpoint or None,
            region_name=s.backup_s3_region or None,
            aws_access_key_id=s.backup_s3_access_key.get_secret_value() or None,
            aws_secret_access_key=s.backup_s3_secret_key.get_secret_value() or None,
        )

    def put(self, name: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=name, Body=data)

    def get(self, name: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=name)["Body"].read()

    def list(self) -> list[str]:
        out, token = [], None
        while True:
            kw = {"Bucket": self.bucket, "Prefix": _PREFIX}
            if token:
                kw["ContinuationToken"] = token
            resp = self.client.list_objects_v2(**kw)
            out += [o["Key"] for o in resp.get("Contents", [])
                    if o["Key"].endswith(_SUFFIX)]
            if not resp.get("IsTruncated"):
                return sorted(out)
            token = resp.get("NextContinuationToken")

    def delete(self, name: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=name)


def _offsite():
    s = get_settings()
    if s.backup_s3_bucket:
        return _S3Store(s)
    if s.backup_offsite_dir:
        return _DirStore(s.backup_offsite_dir)
    raise RuntimeError(
        "No offsite target — set BACKUP_S3_BUCKET or BACKUP_OFFSITE_DIR."
    )


def is_configured() -> bool:
    s = get_settings()
    return bool(s.backup_encryption_key.get_secret_value()
                and (s.backup_s3_bucket or s.backup_offsite_dir))


# ── Alerts ─────────────────────────────────────────────────────────────────

def _alert(message: str) -> None:
    """Loud failure signal: an ERROR log (surfaced in Railway) plus an
    optional webhook POST."""
    logger.error("BACKUP ALERT: %s", message)
    url = get_settings().backup_alert_webhook
    if url:
        try:
            req = urllib.request.Request(  # noqa: S310 — operator-configured https webhook
                url, data=json.dumps({"text": f"[backup] {message}"}).encode(),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            urllib.request.urlopen(req, timeout=10)  # noqa: S310
        except Exception:
            logger.exception("Failed to send backup alert webhook")


# ── Integrity ──────────────────────────────────────────────────────────────

def integrity_check(db_path: Path | None = None) -> bool:
    """PRAGMA integrity_check on the live DB. Returns True if 'ok'."""
    db_path = db_path or (get_settings().data_path / "app.db")
    if not db_path.exists():
        return True  # nothing to check yet
    con = sqlite3.connect(db_path)
    try:
        result = con.execute("PRAGMA integrity_check").fetchone()
    finally:
        con.close()
    ok = bool(result) and result[0] == "ok"
    if not ok:
        _alert(f"integrity_check failed on {db_path.name}: {result}")
    return ok


# ── Create ─────────────────────────────────────────────────────────────────

def _snapshot_db(db_path: Path, dest: Path) -> None:
    """Consistent copy of a live SQLite DB via the online backup API."""
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)  # atomic, safe against concurrent writers
    finally:
        dst.close()
        src.close()


def create_backup() -> str:
    """Snapshot the DB + documents, encrypt, upload offsite, prune. Returns
    the backup name."""
    s = get_settings()
    data = s.data_path
    db_path = data / "app.db"
    staging = data / "backup-staging"
    staging.mkdir(parents=True, exist_ok=True)
    name = _PREFIX + datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + _SUFFIX

    integrity_check(db_path)  # alerts on failure but still backs up (older good copies remain)

    snapshot = staging / "app.db"
    try:
        if db_path.exists():
            _snapshot_db(db_path, snapshot)

        # tar the snapshot + the documents/exports tree in memory.
        tar_buf = io.BytesIO()
        with tarfile.open(fileobj=tar_buf, mode="w:gz") as tar:
            if snapshot.exists():
                tar.add(snapshot, arcname="app.db")
            projects = data / "projects"
            if projects.exists():
                tar.add(projects, arcname="projects")
        token = _fernet().encrypt(tar_buf.getvalue())

        _offsite().put(name, token)
        logger.info("Backup uploaded: %s (%d bytes encrypted)", name, len(token))
        prune()
        return name
    except Exception as exc:
        _alert(f"backup failed: {exc}")
        raise
    finally:
        snapshot.unlink(missing_ok=True)


# ── Retention (daily + monthly) ────────────────────────────────────────────

def _ts(name: str) -> datetime:
    return datetime.strptime(name[len(_PREFIX):len(_PREFIX) + 15], "%Y%m%d-%H%M%S")


def _keepers(names: list[str], daily: int, monthly: int) -> set[str]:
    """Newest-per-day for `daily` days + newest-per-month for `monthly` months."""
    keep, days, months = set(), {}, {}
    for name in sorted(names, reverse=True):  # newest first
        try:
            t = _ts(name)
        except ValueError:
            keep.add(name)  # unparseable — never auto-delete
            continue
        d, m = t.strftime("%Y%m%d"), t.strftime("%Y%m")
        if d not in days and len(days) < daily:
            days[d] = name
            keep.add(name)
        if m not in months and len(months) < monthly:
            months[m] = name
            keep.add(name)
    return keep


def prune() -> list[str]:
    s = get_settings()
    store = _offsite()
    names = store.list()
    keep = _keepers(names, s.backup_retention_daily, s.backup_retention_monthly)
    deleted = []
    for name in names:
        if name not in keep:
            store.delete(name)
            deleted.append(name)
    if deleted:
        logger.info("Pruned %d old backups", len(deleted))
    return deleted


# ── Restore ────────────────────────────────────────────────────────────────

def restore_backup(name: str, target: Path | None = None) -> Path:
    """Download, decrypt and unpack a backup into `target` (default DATA_DIR).
    Restores app.db and the projects/ tree. Returns the target path."""
    target = target or get_settings().data_path
    target.mkdir(parents=True, exist_ok=True)
    token = _offsite().get(name)
    tar_bytes = _fernet().decrypt(token)
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
        tar.extractall(target, filter="data")  # 'data' filter blocks path traversal
    restored = target / "app.db"
    if restored.exists() and not integrity_check(restored):
        raise RuntimeError("Restored database failed its integrity check.")
    logger.info("Restored %s into %s", name, target)
    return target


# ── CLI ────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = argv if argv is not None else sys.argv[1:]
    cmd = args[0] if args else ""

    if cmd == "gen-key":
        from cryptography.fernet import Fernet
        print(Fernet.generate_key().decode())
        return 0

    if cmd == "run":
        if "--if-configured" in args and not is_configured():
            logger.info("Backups not configured — skipping.")
            return 0
        create_backup()
        return 0

    if cmd == "list":
        for n in _offsite().list():
            print(n)
        return 0

    if cmd == "integrity":
        ok = integrity_check()
        print("ok" if ok else "FAILED")
        return 0 if ok else 1

    if cmd == "restore" and len(args) >= 2:
        target = None
        if "--target" in args:
            target = Path(args[args.index("--target") + 1])
        restore_backup(args[1], target)
        print("restored")
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
