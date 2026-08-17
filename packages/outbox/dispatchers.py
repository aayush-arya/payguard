"""Concrete OutboxDispatcher implementations.

Nothing downstream (a real message broker, webhook fan-out) exists yet, so
LoggingDispatcher is the whole "Message/Event Processing" box from the
architecture diagram for now: it durably proves every outbox event reaches
a consumer at least once. Swapping in a real broker later means implementing
a new OutboxDispatcher, not changing packages/outbox/worker.py.
"""

from __future__ import annotations

import logging

from database.models import OutboxEvent

logger = logging.getLogger("payguard.outbox")


class LoggingDispatcher:
    async def dispatch(self, event: OutboxEvent) -> None:
        logger.info(
            "outbox.dispatch event_type=%s aggregate_type=%s aggregate_id=%s payload=%s",
            event.event_type,
            event.aggregate_type,
            event.aggregate_id,
            event.payload,
        )
