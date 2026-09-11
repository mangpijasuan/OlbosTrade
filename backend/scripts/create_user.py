"""
Provision a user account. Invite-only: there is no public registration route.

Self-service signup on a platform that connects to brokers pulls in email
verification, bot defence and abuse response — none of which is worth building
before there is a reason. Until then, accounts are created here.

The password is read from a prompt, never from argv: anything on the command
line lands in shell history and in `ps` output for every other process on the
box.

Usage (inside the container):
    python scripts/create_user.py --email you@example.com
    python scripts/create_user.py --email you@example.com --tier pro
    python scripts/create_user.py --email you@example.com --deactivate
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

sys.path.insert(0, "/app")

from sqlalchemy import select  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.user import TIERS, User  # noqa: E402
from app.services.auth_service import hash_password, normalize_email  # noqa: E402

MIN_PASSWORD_LEN = 12


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--tier", default="free", choices=TIERS)
    parser.add_argument("--deactivate", action="store_true",
                        help="Disable an existing account instead of creating one")
    args = parser.parse_args()

    email = normalize_email(args.email)
    if "@" not in email:
        print(f"'{args.email}' does not look like an email address.")
        return 2

    async with AsyncSessionLocal() as db:
        existing = (await db.execute(
            select(User).where(User.email == email).limit(1)
        )).scalar_one_or_none()

        if args.deactivate:
            if existing is None:
                print(f"No account for {email}.")
                return 1
            existing.is_active = False
            await db.commit()
            # Note: existing sessions are checked against is_active on every
            # request, so this takes effect immediately rather than at expiry.
            print(f"Deactivated {email}. Active sessions stop working on their next request.")
            return 0

        if existing is not None:
            print(f"{email} already exists (tier={existing.tier}, active={existing.is_active}).")
            print("Re-run with --deactivate to disable it. Passwords are not changed here.")
            return 1

        password = getpass.getpass("Password (min 12 chars): ")
        if len(password) < MIN_PASSWORD_LEN:
            print(f"Too short — {MIN_PASSWORD_LEN} characters minimum.")
            return 2
        if password != getpass.getpass("Confirm: "):
            print("Passwords do not match.")
            return 2

        db.add(User(email=email, password_hash=hash_password(password), tier=args.tier))
        await db.commit()

    print(f"Created {email} (tier={args.tier}).")
    print("Set AUTH_ENABLED=true and restart for it to be usable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
