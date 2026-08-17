"""Transactional outbox consumer (ADR-003).

Transaction-boundary note, since this is the one place in the codebase that
deliberately *doesn't* follow the "never hold a DB lock across a network
call" rule from docs/architecture.md section 8: `process_next()` holds one
event's `FOR UPDATE SKIP LOCKED` lock for the duration of `dispatcher.dispatch()`.
That rule exists because payment provider calls are slow, unpredictable,
third-party HTTP requests -- holding a lock across one of those risks a
provider outage turning into a database outage. A Phase 6 dispatcher is a
fast, local, in-process operation (structured logging), so the same risk
doesn't apply, and holding the lock buys real simplicity: a crash mid-dispatch
just rolls the transaction back, leaving the row PENDING and picked up by the
next poll -- no separate PROCESSING-with-staleness-reclaim machinery needed
(contrast with idempotency_keys, which genuinely needs that because it spans
a real network call). If a future phase swaps in a real message broker with
meaningful network latency, this tradeoff should be revisited -- see
docs/outbox.md.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol

from database.models import OutboxEvent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

MAX_ATTEMPTS = 8
BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 300.0


class OutboxDispatcher(Protocol):
    async def dispatch(self, event: OutboxEvent) -> None:
        """Deliver the event. Raise any exception to indicate failure --
        the worker classifies nothing about *why* it failed, since at this
        layer every failure is transient-by-default (retry with backoff
        until MAX_ATTEMPTS, then dead-letter). Unlike payment provider
        errors, there's no equivalent of a permanent DECLINED here."""
        ...


def compute_backoff(attempt_count: int) -> timedelta:
    """Exponential backoff with full jitter, capped at MAX_DELAY_SECONDS.
    `attempt_count` is the number of attempts made so far (>= 1). Full jitter
    (uniform(0, cap) rather than cap +/- a little) is deliberate: it spreads
    out retries from many simultaneously-failing events instead of having
    them all wake up in a synchronized thundering herd."""
    exponential_delay = min(MAX_DELAY_SECONDS, BASE_DELAY_SECONDS * (2 ** (attempt_count - 1)))
    return timedelta(seconds=random.uniform(0, exponential_delay))


async def _claim_one(session: AsyncSession) -> OutboxEvent | None:
    now = datetime.now(UTC)
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.status == "PENDING", OutboxEvent.available_at <= now)
        .order_by(OutboxEvent.available_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def process_next(session: AsyncSession, dispatcher: OutboxDispatcher) -> str | None:
    """Claim and dispatch one due event. Returns the resulting status
    (PROCESSED, PENDING, or DEAD_LETTER), or None if there was nothing to do."""
    event = await _claim_one(session)
    if event is None:
        await session.commit()
        return None

    try:
        await dispatcher.dispatch(event)
    except Exception as exc:
        event.attempt_count += 1
        event.failure_reason = str(exc)[:500]
        if event.attempt_count >= MAX_ATTEMPTS:
            event.status = "DEAD_LETTER"
        else:
            event.available_at = datetime.now(UTC) + compute_backoff(event.attempt_count)
        await session.commit()
        return event.status

    event.status = "PROCESSED"
    await session.commit()
    return event.status


async def run_batch(session: AsyncSession, dispatcher: OutboxDispatcher, *, max_events: int = 50) -> int:
    """Process up to `max_events` due events sequentially on one session.
    Returns the number actually processed (of any outcome)."""
    processed = 0
    for _ in range(max_events):
        result = await process_next(session, dispatcher)
        if result is None:
            break
        processed += 1
    return processed


async def requeue_dead_letter(session: AsyncSession, event_id: uuid.UUID) -> bool:
    """Operator escape hatch: move a DEAD_LETTER event back to PENDING with a
    reset attempt count, for manual replay after the underlying issue (e.g. a
    downstream outage) is fixed. Never happens automatically."""
    event = await session.get(OutboxEvent, event_id)
    if event is None or event.status != "DEAD_LETTER":
        return False
    event.status = "PENDING"
    event.attempt_count = 0
    event.available_at = datetime.now(UTC)
    event.failure_reason = None
    await session.commit()
    return True
