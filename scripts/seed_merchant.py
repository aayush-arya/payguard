"""Create a merchant and print a usable API key.

There is no merchant-creation HTTP endpoint by design (docs/architecture.md
section 16's API list is entirely payment/refund/webhook operations) --
merchant provisioning is an out-of-band, operator-driven action, same as it
is on most real payment platforms. This script is that out-of-band path for
local development and testing. The raw API key is only ever shown here, once
-- only its hash is stored (domain.security.hash_api_key).

Usage:
    python scripts/seed_merchant.py "Demo Merchant"
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

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


async def main(name: str) -> None:
    from database.models import Merchant
    from database.session import get_sessionmaker
    from domain.security import generate_api_key, hash_api_key

    api_key = generate_api_key()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        merchant = Merchant(name=name, api_key_hash=hash_api_key(api_key))
        session.add(merchant)
        await session.commit()
        print(f"Created merchant: {merchant.id} ({name})")
        print(f"API key (shown once, store it now): {api_key}")


if __name__ == "__main__":
    merchant_name = sys.argv[1] if len(sys.argv) > 1 else "Demo Merchant"
    asyncio.run(main(merchant_name))
