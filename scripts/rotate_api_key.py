"""Rotate a merchant's API key, out-of-band, same reasoning as
scripts/seed_merchant.py: credential lifecycle is an operator action, not
a self-service endpoint a merchant's own (possibly-compromised) key could
call against itself.

The old key keeps working for a 24-hour overlap window (packages/merchants/
service.py's rotate_api_key()) so an in-flight deploy of the new key
doesn't cause an outage the moment this script returns.

Usage:
    python scripts/rotate_api_key.py <merchant-id>
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "packages"))


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


async def main(merchant_id: uuid.UUID) -> None:
    from database.models import Merchant
    from database.session import get_sessionmaker
    from domain.errors import PayGuardError
    from merchants import rotate_api_key

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        merchant = await session.get(Merchant, merchant_id)
        if merchant is None:
            raise PayGuardError("MERCHANT_NOT_FOUND", f"No merchant found with id {merchant_id}.")

        new_api_key = await rotate_api_key(merchant)
        await session.commit()
        print(f"Rotated API key for merchant: {merchant.id} ({merchant.name})")
        print(f"New API key (shown once, store it now): {new_api_key}")
        print(f"Old key remains valid until: {merchant.previous_api_key_expires_at.isoformat()}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/rotate_api_key.py <merchant-id>", file=sys.stderr)
        raise SystemExit(1)
    asyncio.run(main(uuid.UUID(sys.argv[1])))
