"""
User administration (BRD 2.10: no self-registration).

    python -m app.manage add-user broker@ukcib.co.uk
    python -m app.manage set-password broker@ukcib.co.uk   # rotate a password
    python -m app.manage list-users
    python -m app.manage remove-user broker@ukcib.co.uk
    python -m app.manage logout-all                        # invalidate every session

Passwords are prompted (never taken as a command-line argument, so they
stay out of shell history) and must satisfy the policy in app/core/startup.py.
"""

import getpass
import sys

from app.core import auth, db
from app.core.startup import password_problem


def _prompt_password(email: str) -> str | None:
    password = getpass.getpass(f"Password for {email}: ")
    problem = password_problem(password)
    if problem:
        print(f"Password {problem}.")
        return None
    return password


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    cmd = args[0]

    if cmd == "add-user" and len(args) >= 2:
        email = args[1].strip().lower()
        password = _prompt_password(email)
        if password is None:
            return 1
        auth.create_user(email, password)
        print(f"Created {email}")
        return 0

    if cmd == "set-password" and len(args) >= 2:
        email = args[1].strip().lower()
        if not db.query_one("SELECT id FROM users WHERE email=?", (email,)):
            print(f"No such user: {email}")
            return 1
        password = _prompt_password(email)
        if password is None:
            return 1
        db.execute("UPDATE users SET password_hash=? WHERE email=?",
                   (auth.hash_password(password), email))
        # Invalidate that user's existing sessions on a password change.
        db.execute(
            "DELETE FROM sessions WHERE user_id=(SELECT id FROM users WHERE email=?)",
            (email,),
        )
        print(f"Password rotated for {email} (their sessions were signed out)")
        return 0

    if cmd == "list-users":
        for row in db.query("SELECT email, created FROM users ORDER BY email"):
            print(row["email"])
        return 0

    if cmd == "remove-user" and len(args) >= 2:
        db.execute("DELETE FROM users WHERE email=?", (args[1].strip().lower(),))
        print(f"Removed {args[1]}")
        return 0

    if cmd == "logout-all":
        db.execute("DELETE FROM sessions")
        print("All sessions invalidated — every user must sign in again.")
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
