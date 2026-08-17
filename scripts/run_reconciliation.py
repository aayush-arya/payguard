"""On-demand reconciliation pass (ADR-008).

There is no scheduler or dashboard trigger yet (Phase 12/13) -- this script
is the on-demand path ADR-008 describes ("triggered on-demand (dashboard
button, demo scenario)"), runnable directly against the real database.

Usage:
    python scripts/run_reconciliation.py
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


async def main() -> None:
    from database.session import get_sessionmaker
    from providers import MockProvider
    from reconciliation import run_reconciliation_pass

    # A fresh MockProvider here has no memory of any authorize() calls made
    # by a running API process (it's an in-memory mock, not a real service) --
    # this script is only useful when run against the same provider instance
    # the API used, i.e. as a demo/test harness, not as a real operational
    # tool. A real provider adapter wouldn't have this limitation.
    sessionmaker = get_sessionmaker()
    provider = MockProvider()

    async with sessionmaker() as session:
        reports = await run_reconciliation_pass(session, provider)

    if not reports:
        print("No payments needed reconciliation.")
        return

    for report in reports:
        print(
            f"payment_id={report.payment_intent_id} result={report.result} "
            f"internal_status={report.internal_status} provider_status={report.provider_status}"
        )


if __name__ == "__main__":
    asyncio.run(main())
