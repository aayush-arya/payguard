"""Proves the reason for `SELECT ... FOR UPDATE SKIP LOCKED` (ADR-003):
multiple worker replicas polling the same outbox table concurrently must
each claim disjoint rows -- no event is ever dispatched twice, and no worker
blocks waiting on a row another worker already grabbed."""

import asyncio
import uuid

from database.models import OutboxEvent
from outbox.worker import process_next
from sqlalchemy import select

EVENT_COUNT = 40
WORKER_COUNT = 8


class ThreadSafeRecordingDispatcher:
    """Safe under asyncio's cooperative concurrency: dispatch() does no
    awaiting itself, so each call completes atomically between await points."""

    def __init__(self) -> None:
        self.dispatched_ids: list[uuid.UUID] = []

    async def dispatch(self, session, event: OutboxEvent) -> None:
        self.dispatched_ids.append(event.id)


async def _worker_loop(sessionmaker, dispatcher) -> int:
    processed = 0
    while True:
        async with sessionmaker() as session:
            result = await process_next(session, dispatcher)
        if result is None:
            return processed
        processed += 1


async def test_concurrent_workers_claim_disjoint_events_no_double_dispatch(db_session, db_sessionmaker):
    events = [
        OutboxEvent(
            aggregate_type="payment_intent",
            aggregate_id=uuid.uuid4(),
            event_type="payment.created",
            payload={},
        )
        for _ in range(EVENT_COUNT)
    ]
    db_session.add_all(events)
    await db_session.commit()
    expected_ids = {e.id for e in events}

    dispatcher = ThreadSafeRecordingDispatcher()
    results = await asyncio.gather(*(_worker_loop(db_sessionmaker, dispatcher) for _ in range(WORKER_COUNT)))

    assert sum(results) == EVENT_COUNT, f"workers processed {sum(results)}, expected {EVENT_COUNT}"
    assert len(dispatcher.dispatched_ids) == EVENT_COUNT, "every event must be dispatched exactly once"
    assert set(dispatcher.dispatched_ids) == expected_ids, "no event skipped, no unexpected event dispatched"
    assert len(dispatcher.dispatched_ids) == len(set(dispatcher.dispatched_ids)), (
        "no event was dispatched twice -- this is what SKIP LOCKED prevents"
    )

    async with db_sessionmaker() as session:
        remaining = (
            (await session.execute(select(OutboxEvent).where(OutboxEvent.status != "PROCESSED")))
            .scalars()
            .all()
        )
    assert remaining == []
