"""Create the first owner account.

    python -m app.create_owner --name "Balaji Rao" --email owner@firm.com

There is no public sign-up in this product — every account is created by an
Owner from the Team screen — which leaves a chicken-and-egg problem on a fresh
deployment. This is the way out of it.

It exists as a module rather than a documented shell snippet because Render's
free instances have no Shell tab, so the realistic path is running this from a
laptop against the database's *external* connection string:

    DATABASE_URL='postgresql://…@…render.com/balaji_crm' \\
        python -m app.create_owner --name "Balaji Rao" --email owner@firm.com

Deliberately refuses to create a second owner unless forced: the common
accident is running it twice and ending up unsure which password is live.
"""

from __future__ import annotations

import argparse
import getpass
import secrets
import sys

from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError

from app.db import SessionLocal, system_scope
from app.models import ROLE_OWNER, User
from app.security import hash_password

MIN_PASSWORD_LENGTH = 8


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--password",
        help=(
            "Omit to be prompted, which keeps it out of your shell history. "
            "Omit --password and pass --generate for a random one."
        ),
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate a strong password and print it once.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Create even if an owner already exists.",
    )
    args = parser.parse_args(argv)

    email = args.email.strip().lower()

    if args.generate:
        password = secrets.token_urlsafe(16)
    elif args.password:
        password = args.password
    else:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Confirm: "):
            print("Passwords did not match.", file=sys.stderr)
            return 2

    if len(password) < MIN_PASSWORD_LENGTH:
        print(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
            file=sys.stderr,
        )
        return 2

    db = SessionLocal()
    try:
        # Infrastructure work with no principal to scope by — the same
        # justification app/seed.py and the auth path use.
        with system_scope():
            # The likeliest way to reach this script is a fresh deployment, so
            # the likeliest failure is pointing it at a database whose schema
            # has not been created yet. Say that, instead of a 40-line
            # SQLAlchemy traceback that buries the one useful sentence.
            try:
                db.execute(select(User.id).limit(1)).first()
            except ProgrammingError as exc:
                if "does not exist" in str(exc):
                    print(
                        "The database has no schema yet. Run migrations first:\n"
                        "    alembic upgrade head",
                        file=sys.stderr,
                    )
                    return 3
                raise

            if db.execute(
                select(User.id).where(User.email == email)
            ).first():
                print(f"A user with {email} already exists.", file=sys.stderr)
                return 1

            existing_owner = db.execute(
                select(User.email)
                .where(User.role == ROLE_OWNER)
                .where(User.deleted_at.is_(None))
            ).first()
            if existing_owner and not args.force:
                print(
                    f"An owner already exists ({existing_owner[0]}). "
                    "Add further staff from the Team screen, or pass --force.",
                    file=sys.stderr,
                )
                return 1

            db.add(
                User(
                    name=args.name.strip(),
                    email=email,
                    role=ROLE_OWNER,
                    password_hash=hash_password(password),
                    is_available=True,
                )
            )
            db.commit()
    finally:
        db.close()

    print(f"Owner created: {email}")
    if args.generate:
        print(f"Password:      {password}")
        print("Save it now — it is not stored anywhere in readable form.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
