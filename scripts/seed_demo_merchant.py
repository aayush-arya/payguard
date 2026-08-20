"""Seed the one merchant whose API key is meant to be public: the dashboard's
own "try it now" demo key, shown directly on the Connect screen
(frontend/src/pages/Connect.tsx) so anyone opening the dashboard can explore
it without running scripts/seed_merchant.py first.

This is the one deliberate exception to "an API key is a secret, shown
once" (scripts/seed_merchant.py's own docstring) -- a fixed, publicly-known
key is exactly right for a demo merchant that only ever touches
MockProvider and fake money, and wrong for anything else. Idempotent: safe
to run every time the app starts (see docker-compose.prod.yml / a real
deploy's init step) without creating duplicate demo merchants or rotating
the key out from under anyone who already has it saved.

Usage:
    python scripts/seed_demo_merchant.py
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "packages"))

# Public by design -- never treat this as a leaked secret, and never reuse
# this constant/pattern for a real merchant's key.
DEMO_API_KEY = "sk_test_demo_public_9f3a7c2e1b6d4f8a0c5e9b2d7f1a4c6e"
DEMO_MERCHANT_NAME = "Demo Merchant"


def _load_dotenv() -> None:
    import os

    env_path = pathlib.Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


async def main() -> None:
    from database.models import Merchant
    from database.session import get_sessionmaker
    from domain.security import hash_api_key
    from sqlalchemy import select

    key_hash = hash_api_key(DEMO_API_KEY)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        existing = (
            await session.execute(select(Merchant).where(Merchant.api_key_hash == key_hash))
        ).scalar_one_or_none()
        if existing is not None:
            print(f"Demo merchant already exists: {existing.id} ({existing.name})")
            print(f"Demo API key: {DEMO_API_KEY}")
            return

        merchant = Merchant(name=DEMO_MERCHANT_NAME, api_key_hash=key_hash)
        session.add(merchant)
        await session.commit()
        print(f"Created demo merchant: {merchant.id} ({DEMO_MERCHANT_NAME})")
        print(f"Demo API key: {DEMO_API_KEY}")


if __name__ == "__main__":
    asyncio.run(main())
