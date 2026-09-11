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


def login(email: str, password: str) -> tuple[str, str] | None:
    """Returns (session_token, csrf_token), or None on bad credentials (one
    message for both wrong email and wrong password — no account probing)."""
    row = db.query_one(
        "SELECT id, password_hash FROM users WHERE email=?",
        (email.strip().lower(),),
    )
    if row is None or not verify_password(password, row["password_hash"]):
        return None
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
    # The `expires > now` filter already rejects an expired session, so no
    # cleanup DELETE is needed on every auth check — that housekeeping runs
    # periodically in the background instead (see delete_expired_sessions).
    row = db.query_one(
        "SELECT u.id, u.email, u.name FROM sessions s "
        "JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash=? AND s.expires > ?",
        (_token_hash(token), db.now()),
    )
    return dict(row) if row else None


def delete_expired_sessions() -> None:
    """Remove sessions past their expiry. Run periodically in the
    background (and once at startup) — never on the per-request auth path,
    so an auth check stays a single fast SELECT."""
    db.execute("DELETE FROM sessions WHERE expires <= ?", (db.now(),))


def require_user(qct_session: str | None = Cookie(default=None)) -> dict:
    """FastAPI dependency guarding every data endpoint (BRD 2.11: access
    limited to the named users)."""
    user = user_for_token(qct_session)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in required.")
    return user
