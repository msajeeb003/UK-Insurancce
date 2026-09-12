"""
Startup configuration checks and the admin-password policy.

In production these are fatal — the process refuses to boot on a misconfig
(insecure cookie, weak admin password, no LLM key) so a bad deploy fails fast
instead of running insecure. In development they are lenient.
"""

import logging

from app.core.config import get_settings

logger = logging.getLogger("app.startup")

# Obvious weak/default passwords rejected outright (case-insensitive).
_WEAK_PASSWORDS = {
    "changeme", "password", "password123", "admin", "administrator",
    "adminadmin", "letmein", "12345678", "123456789012", "insurance",
    "local-dev-password-1", "qwertyuiop", "brokerbroker",
}

# ADMIN_PASSWORD policy (documented in docs/KEY_ROTATION.md):
#   >= 12 characters, not a known weak/default, and a reasonable mix of
#   distinct characters.
MIN_PASSWORD_LEN = 12


def password_problem(password: str) -> str | None:
    """Return a human-readable reason the password is unacceptable, or None."""
    if len(password) < MIN_PASSWORD_LEN:
        return f"must be at least {MIN_PASSWORD_LEN} characters"
    if password.lower() in _WEAK_PASSWORDS:
        return "is a known weak/default password"
    if len(set(password)) < 5:
        return "must use a wider variety of characters"
    return None


def is_production() -> bool:
    return get_settings().app_env.strip().lower() == "production"


def run_startup_checks() -> None:
    """Fail fast on an insecure production configuration; advise in dev."""
    s = get_settings()
    prod = is_production()
    fatal: list[str] = []

    if prod:
        if not s.cookie_secure:
            fatal.append(
                "COOKIE_SECURE must be true in production (HTTPS-only, so the "
                "session cookie is never sent over plain HTTP)."
            )
        pw = s.admin_password.get_secret_value()
        if pw:
            problem = password_problem(pw)
            if problem:
                fatal.append(f"ADMIN_PASSWORD {problem}.")
        if not (s.anthropic_api_key.get_secret_value()
                or s.openai_api_key.get_secret_value()):
            fatal.append(
                "No LLM provider key set (ANTHROPIC_API_KEY or OPENAI_API_KEY)."
            )

    if fatal:
        raise RuntimeError(
            "Refusing to start — production configuration errors:\n - "
            + "\n - ".join(fatal)
        )

    # Non-fatal advisories (don't block boot, but should be addressed).
    if prod and not s.backup_encryption_key.get_secret_value():
        logger.warning("Production without backups configured — see docs/BACKUP.md")
    if prod and not s.sentry_dsn:
        logger.warning("Production without Sentry configured — see docs/OBSERVABILITY.md")
