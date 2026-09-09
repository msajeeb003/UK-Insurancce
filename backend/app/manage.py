"""
User administration (BRD 2.10: no self-registration).

    python -m app.manage add-user broker@ukcib.co.uk
    python -m app.manage list-users
    python -m app.manage remove-user broker@ukcib.co.uk

Passwords are prompted (never taken as a command-line argument, so they
stay out of shell history).
"""

import getpass
import sys

from app.core import auth, db


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    cmd = args[0]
    if cmd == "add-user" and len(args) >= 2:
        email = args[1].strip().lower()
        password = getpass.getpass(f"Password for {email}: ")
        if len(password) < 8:
            print("Password must be at least 8 characters.")
            return 1
        auth.create_user(email, password)
        print(f"Created {email}")
        return 0
    if cmd == "list-users":
        for row in db.query("SELECT email, created FROM users ORDER BY email"):
            print(row["email"])
        return 0
    if cmd == "remove-user" and len(args) >= 2:
        db.execute("DELETE FROM users WHERE email=?", (args[1].strip().lower(),))
        print(f"Removed {args[1]}")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
