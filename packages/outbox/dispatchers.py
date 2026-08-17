"""Concrete OutboxDispatcher implementations.

No real message broker exists yet, so LoggingDispatcher is the whole
"Message/Event Processing" box from the architecture diagram for most event
types -- it durably proves every outbox event reaches a consumer at least
once. WebhookEffectDispatcher additionally applies the one event type that
does have a real, built consumer as of Phase 7: `webhook.received`, which it
routes to webhooks.service.apply_webhook_event() using the same session the
outbox worker is holding the event's lock under (see packages/outbox/worker.py
and docs/outbox.md for why that matters).
"""

from __future__ import annotations

import logging
import uuid

from database.models import OutboxEvent
from sqlalchemy.ext.asyncio import AsyncSession
from webhooks.service import apply_webhook_event

logger = logging.getLogger("payguard.outbox")


class LoggingDispatcher:
    async def dispatch(self, session: AsyncSession, event: OutboxEvent) -> None:
        logger.info(
            "outbox.dispatch event_type=%s aggregate_type=%s aggregate_id=%s payload=%s",
            event.event_type,
            event.aggregate_type,
            event.aggregate_id,
            event.payload,
        )


class WebhookEffectDispatcher:
    """The default dispatcher for apps/worker: logs every event (so nothing
    is silently unobserved) and, for `webhook.received` events specifically,
    applies the webhook's effect on the referenced payment."""

    def __init__(self) -> None:
        self._logging = LoggingDispatcher()

    async def dispatch(self, session: AsyncSession, event: OutboxEvent) -> None:
        await self._logging.dispatch(session, event)
        if event.event_type != "webhook.received":
            return
        webhook_event_id = uuid.UUID(event.payload["webhook_event_id"])
        await apply_webhook_event(session, webhook_event_id)
