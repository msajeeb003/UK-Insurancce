"""
Authentication (BRD 2.10 / S1): simple secure email + password login.

- No self-registration: users are seeded from ADMIN_EMAIL/ADMIN_PASSWORD
  on first startup and added with `python -m app.manage add-user`.
- Passwords: scrypt (stdlib) with a per-user salt — never stored or
  logged in clear.
- Sessions: a random token in an HttpOnly cookie; only its SHA-256 hash
  is stored server-side, so a database leak leaks no usable tokens.
- Identical permissions for every user; all users see all projects.
"""

import hashlib
import logging
import secrets
import sqlite3

from fastapi import Cookie, HTTPException

from app.core import db
from app.core.config import get_settings

logger = logging.getLogger(__name__)

COOKIE_NAME = "qct_session"

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT
        )
        return secrets.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def create_user(email: str, password: str, name: str = "") -> None:
    db.execute(
        "INSERT INTO users (email, name, password_hash, created) VALUES (?,?,?,?)",
        (email.strip().lower(), name, hash_password(password), db.now()),
    )


def seed_admin_if_empty() -> None:
    """First deployment: create the initial user from the environment."""
    if db.query_one("SELECT id FROM users LIMIT 1"):
        return
    settings = get_settings()
    email = settings.admin_email.strip().lower()
    password = settings.admin_password.get_secret_value()
    if email and password:
        # Enforce the password policy at seed time (fatal in production; the
        # startup check has already run, so this is defence in depth).
        from app.core.startup import is_production, password_problem
        problem = password_problem(password)
        if problem and is_production():
            raise RuntimeError(f"ADMIN_PASSWORD {problem}.")
        if problem:
            logger.warning("ADMIN_PASSWORD %s (allowed in development only)", problem)
        try:
            create_user(email, password)
            logger.info("Seeded initial user %s from ADMIN_EMAIL", email)
        except sqlite3.IntegrityError:
            # Multiple gunicorn workers can start together and race to seed;
            # the UNIQUE(email) constraint means only the first wins, and
            # that is fine — the user exists.
            logger.info("Initial user already seeded by another worker")
    else:
        logger.warning(
            "No users exist and ADMIN_EMAIL/ADMIN_PASSWORD are not set — "
            "nobody can sign in until a user is created."
        )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(user_id: int) -> tuple[str, str]:
    """Create a session. Returns (session_token, csrf_token): the session
    token goes into the HttpOnly cookie; the CSRF token is handed to the
    frontend to echo back in the X-CSRF-Token header on state-changing
    requests (double-submit protection against cross-site forgery)."""
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    ttl = get_settings().session_ttl_hours * 3600
    db.execute(
        "INSERT INTO sessions (token_hash, user_id, expires, csrf_token) "
        "VALUES (?,?,?,?)",
        (_token_hash(token), user_id, db.now() + ttl, csrf),
    )
    return token, csrf


def end_session(token: str) -> None:
    db.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))


# ── Login throttle / lockout (per account AND per IP) ───────────────────────

class LockedOut(Exception):
    """Raised when an account or IP is temporarily locked after too many
    failed logins. `retry_after` is seconds until it clears."""

    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__("Too many failed attempts.")


def _throttle_locked(key: str) -> float:
    """Seconds remaining on a lock for this key, or 0 if not locked."""
    row = db.query_one("SELECT locked_until FROM login_throttle WHERE key=?", (key,))
    if row and row["locked_until"] > db.now():
        return row["locked_until"] - db.now()
    return 0


def _register_failure(key: str) -> None:
    """Count a failed attempt for a key; lock it once the threshold is hit."""
    s = get_settings()
    row = db.query_one("SELECT failed FROM login_throttle WHERE key=?", (key,))
    failed = (row["failed"] if row else 0) + 1
    locked_until = db.now() + s.login_lockout_minutes * 60 if failed >= s.login_max_attempts else 0
    db.execute(
        "INSERT INTO login_throttle (key, failed, locked_until, updated) "
        "VALUES (?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
        "failed=excluded.failed, locked_until=excluded.locked_until, updated=excluded.updated",
        (key, failed, locked_until, db.now()),
    )


def clear_throttle(key: str) -> None:
    db.execute("DELETE FROM login_throttle WHERE key=?", (key,))


def login(email: str, password: str, ip: str = "") -> tuple[str, str] | None:
    """Returns (session_token, csrf_token), or None on bad credentials (one
    message for both wrong email and wrong password — no account probing).
    Raises LockedOut when the account or IP is temporarily locked."""
    email = email.strip().lower()
    acct_key, ip_key = f"acct:{email}", f"ip:{ip}"

    # Reject early if either the account or the source IP is locked.
    remaining = max(_throttle_locked(acct_key), _throttle_locked(ip_key) if ip else 0)
    if remaining > 0:
        raise LockedOut(int(remaining))

    row = db.query_one(
        "SELECT id, password_hash FROM users WHERE email=?", (email,)
    )
    if row is None or not verify_password(password, row["password_hash"]):
        _register_failure(acct_key)
        if ip:
            _register_failure(ip_key)
        return None

    # Success clears the counters for this account and IP.
    clear_throttle(acct_key)
    if ip:
        clear_throttle(ip_key)
    return start_session(row["id"])


def csrf_token_for(token: str | None) -> str | None:
    """The CSRF token bound to a live session, or None if the session is
    missing/expired. The middleware compares this against X-CSRF-Token."""
    if not token:
        return None
    row = db.query_one(
        "SELECT csrf_token FROM sessions WHERE token_hash=? AND expires > ?",
        (_token_hash(token), db.now()),
    )
    return row["csrf_token"] if row else None


def user_for_token(token: str | None) -> dict | None:
    if not token:
        return None
    # The `expires > now` filter rejects an absolutely-expired session; the
    # inactivity check below rejects one idle too long. Cleanup DELETEs run in
    # the background, not on this hot path.
    row = db.query_one(
        "SELECT u.id, u.email, u.name, s.last_seen FROM sessions s "
        "JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash=? AND s.expires > ?",
        (_token_hash(token), db.now()),
    )
    if row is None:
        return None

    now = db.now()
    timeout = get_settings().inactivity_timeout_minutes * 60
    last_seen = row["last_seen"]
    # last_seen == 0 means a pre-upgrade session — grandfather it (treat as
    # active) and stamp it now.
    if timeout and last_seen and now - last_seen > timeout:
        return None                                   # idle too long → signed out
    # Throttle the write: refresh last_seen at most once a minute.
    if now - last_seen > 60:
        db.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?",
                   (now, _token_hash(token)))
    return {"id": row["id"], "email": row["email"], "name": row["name"]}


def delete_expired_sessions() -> None:
    """Remove sessions past their absolute expiry or idle beyond the
    inactivity timeout. Runs in the background, not on the auth hot path."""
    db.execute("DELETE FROM sessions WHERE expires <= ?", (db.now(),))
    timeout = get_settings().inactivity_timeout_minutes * 60
    if timeout:
        # last_seen > 0 excludes grandfathered sessions from idle-deletion.
        db.execute(
            "DELETE FROM sessions WHERE last_seen > 0 AND last_seen < ?",
            (db.now() - timeout,),
        )


def require_user(qct_session: str | None = Cookie(default=None)) -> dict:
    """FastAPI dependency guarding every data endpoint (BRD 2.11: access
    limited to the named users)."""
    user = user_for_token(qct_session)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in required.")
    return user
