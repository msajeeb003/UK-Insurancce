"""Login lockout/throttle, inactivity timeout, admin reset (auth hardening)."""

import pytest

from app.core import auth, db
from app.core.config import get_settings
from tests.conftest import TEST_USER


def _clear_throttle_for(email: str) -> None:
    auth.clear_throttle(f"acct:{email}")
    for row in db.query("SELECT key FROM login_throttle WHERE key LIKE 'ip:%'"):
        auth.clear_throttle(row["key"])


# ── Lockout ─────────────────────────────────────────────────────────────────

def test_lockout_triggers_and_admin_unlock_clears(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "login_max_attempts", 3)
    monkeypatch.setattr(s, "login_lockout_minutes", 15)
    _clear_throttle_for(TEST_USER[0])

    # 3 wrong attempts -> 4th is locked out (429), even with the RIGHT password
    for _ in range(3):
        r = client.post("/auth/login", json={"email": TEST_USER[0], "password": "wrong"})
        assert r.status_code == 401
    r = client.post("/auth/login", json={"email": TEST_USER[0], "password": TEST_USER[1]})
    assert r.status_code == 429
    assert r.headers.get("Retry-After")

    # Admin unlock clears it; correct login then works.
    auth.clear_throttle(f"acct:{TEST_USER[0]}")
    _clear_throttle_for(TEST_USER[0])
    r = client.post("/auth/login", json={"email": TEST_USER[0], "password": TEST_USER[1]})
    assert r.status_code == 200


def test_lockout_clears_after_cooldown(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "login_max_attempts", 2)
    monkeypatch.setattr(s, "login_lockout_minutes", 15)
    email = "cooldown@test.local"
    if not db.query_one("SELECT id FROM users WHERE email=?", (email,)):
        auth.create_user(email, "Zurich-Atradius-2026!")
    _clear_throttle_for(email)

    for _ in range(2):
        assert auth.login(email, "wrong", "1.2.3.4") is None
    with pytest.raises(auth.LockedOut):
        auth.login(email, "Zurich-Atradius-2026!", "1.2.3.4")

    # Simulate the cooldown elapsing by ageing the lock into the past.
    db.execute("UPDATE login_throttle SET locked_until=? WHERE key=?",
               (db.now() - 1, f"acct:{email}"))
    db.execute("UPDATE login_throttle SET locked_until=? WHERE key=?",
               (db.now() - 1, "ip:1.2.3.4"))
    assert auth.login(email, "Zurich-Atradius-2026!", "1.2.3.4") is not None
    db.execute("DELETE FROM users WHERE email=?", (email,))


# ── Inactivity timeout ──────────────────────────────────────────────────────

def test_inactivity_timeout_logs_out(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "inactivity_timeout_minutes", 30)
    email = "idle@test.local"
    if not db.query_one("SELECT id FROM users WHERE email=?", (email,)):
        auth.create_user(email, "Zurich-Atradius-2026!")
    token, _ = auth.login(email, "Zurich-Atradius-2026!", "5.6.7.8")

    # Fresh session resolves to the user.
    assert auth.user_for_token(token) is not None

    # Age last_seen beyond the timeout -> session no longer valid.
    from app.core.auth import _token_hash
    db.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?",
               (db.now() - 31 * 60, _token_hash(token)))
    assert auth.user_for_token(token) is None
    db.execute("DELETE FROM users WHERE email=?", (email,))


def test_grandfathered_session_last_seen_zero_is_allowed(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "inactivity_timeout_minutes", 30)
    email = "grand@test.local"
    if not db.query_one("SELECT id FROM users WHERE email=?", (email,)):
        auth.create_user(email, "Zurich-Atradius-2026!")
    token, _ = auth.login(email, "Zurich-Atradius-2026!", "9.9.9.9")
    from app.core.auth import _token_hash
    db.execute("UPDATE sessions SET last_seen=0 WHERE token_hash=?", (_token_hash(token),))
    assert auth.user_for_token(token) is not None    # not idle-killed
    db.execute("DELETE FROM users WHERE email=?", (email,))


# ── Admin reset ─────────────────────────────────────────────────────────────

def test_admin_reset_password(client):
    from app.manage import main as manage_main
    email = "resetme@test.local"
    if not db.query_one("SELECT id FROM users WHERE email=?", (email,)):
        auth.create_user(email, "Zurich-Atradius-2026!")
    # a live session that should be invalidated by the reset
    old_token, _ = auth.login(email, "Zurich-Atradius-2026!", "")
    assert auth.user_for_token(old_token) is not None

    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert manage_main(["reset-password", email]) == 0
    out = buf.getvalue()
    assert "Temporary password" in out
    temp = out.split("Temporary password for")[1].split(":")[1].split()[0].strip()

    # old session gone; the temp password works and meets the policy
    assert auth.user_for_token(old_token) is None
    from app.core.startup import password_problem
    assert password_problem(temp) is None
    assert auth.login(email, temp, "") is not None
    db.execute("DELETE FROM users WHERE email=?", (email,))
