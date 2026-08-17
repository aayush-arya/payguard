"""Outbox worker process (docs/architecture.md section 10 / ADR-003).

Polls for due outbox_events and dispatches them. Runs as its own process/
container, independent of the API's request/response cycle -- this is why
it's a separate deployable in docker-compose.yml and the Kubernetes manifests
(later phases), not a background task inside the API process: it must keep
retrying regardless of whether the API that originally wrote the event is
still running.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "packages"))


def _load_dotenv() -> None:
    import os

    env_path = pathlib.Path(__file__).resolve().parent.parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("payguard.worker")

POLL_INTERVAL_SECONDS = 1.0
IDLE_POLL_INTERVAL_SECONDS = 5.0
BATCH_SIZE = 50


async def main() -> None:
    from database.session import get_sessionmaker
    from outbox import WebhookEffectDispatcher, run_batch

    sessionmaker = get_sessionmaker()
    dispatcher = WebhookEffectDispatcher()
    logger.info(
        "outbox worker starting, poll_interval=%ss idle_interval=%ss",
        POLL_INTERVAL_SECONDS,
        IDLE_POLL_INTERVAL_SECONDS,
    )

    while True:
        async with sessionmaker() as session:
            processed = await run_batch(session, dispatcher, max_events=BATCH_SIZE)
        if processed:
            logger.info("processed %d outbox event(s)", processed)
        await asyncio.sleep(POLL_INTERVAL_SECONDS if processed else IDLE_POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
