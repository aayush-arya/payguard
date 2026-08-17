"""Integration tests for the outbox worker (ADR-003) against real Postgres:
retry-with-backoff, dead-lettering after MAX_ATTEMPTS, the operator requeue
escape hatch, respecting available_at, and -- critically -- that the outbox
events Phase 3's payment API already writes transactionally actually get
picked up and dispatched by this worker with no changes to the producer."""

import uuid
from datetime import UTC, datetime, timedelta

from database.models import OutboxEvent
from outbox.worker import MAX_ATTEMPTS, process_next, requeue_dead_letter, run_batch
from sqlalchemy import select, update


class RecordingDispatcher:
    def __init__(self) -> None:
        self.dispatched_ids: list[uuid.UUID] = []
        self.fail_counts: dict[uuid.UUID, int] = {}
        self.always_fail_ids: set[uuid.UUID] = set()

    async def dispatch(self, session, event: OutboxEvent) -> None:
        if event.id in self.always_fail_ids:
            raise RuntimeError("simulated permanent dispatch failure")
        remaining = self.fail_counts.get(event.id, 0)
        if remaining > 0:
            self.fail_counts[event.id] = remaining - 1
            raise RuntimeError("simulated transient dispatch failure")
        self.dispatched_ids.append(event.id)


def _make_event(**overrides) -> OutboxEvent:
    defaults = dict(
        aggregate_type="payment_intent",
        aggregate_id=uuid.uuid4(),
        event_type="payment.created",
        payload={"foo": "bar"},
    )
    defaults.update(overrides)
    return OutboxEvent(**defaults)


async def _force_available_now(db_session, event_id: uuid.UUID) -> None:
    await db_session.execute(
        update(OutboxEvent).where(OutboxEvent.id == event_id).values(available_at=datetime.now(UTC))
    )
    await db_session.commit()


async def test_run_batch_processes_all_pending_events(db_session):
    events = [_make_event(event_type=f"evt.{i}") for i in range(5)]
    db_session.add_all(events)
    await db_session.commit()

    dispatcher = RecordingDispatcher()
    processed = await run_batch(db_session, dispatcher)

    assert processed == 5
    assert len(dispatcher.dispatched_ids) == 5
    assert set(dispatcher.dispatched_ids) == {e.id for e in events}

    refreshed = (await db_session.execute(select(OutboxEvent))).scalars().all()
    assert all(e.status == "PROCESSED" for e in refreshed)


async def test_event_not_yet_available_is_not_claimed(db_session):
    event = _make_event(available_at=datetime.now(UTC) + timedelta(hours=1))
    db_session.add(event)
    await db_session.commit()

    dispatcher = RecordingDispatcher()
    processed = await run_batch(db_session, dispatcher)

    assert processed == 0
    assert dispatcher.dispatched_ids == []


async def test_failed_dispatch_is_retried_and_eventually_succeeds(db_session):
    event = _make_event()
    db_session.add(event)
    await db_session.commit()

    dispatcher = RecordingDispatcher()
    dispatcher.fail_counts[event.id] = 2

    # Full jitter backoff can legitimately schedule a delay close to zero,
    # so asserting available_at is still in the future *after* the call
    # (and after a real DB round-trip) is flaky by construction. Instead,
    # assert it's no earlier than "now" was *before* the call -- compute_backoff
    # only ever adds a non-negative delay to the moment it runs.
    before_call = datetime.now(UTC)
    first = await process_next(db_session, dispatcher)
    assert first == "PENDING"
    await db_session.refresh(event)
    assert event.attempt_count == 1
    assert event.failure_reason is not None
    assert event.available_at >= before_call  # a real backoff was scheduled

    await _force_available_now(db_session, event.id)
    second = await process_next(db_session, dispatcher)
    assert second == "PENDING"

    await _force_available_now(db_session, event.id)
    third = await process_next(db_session, dispatcher)
    assert third == "PROCESSED"
    assert dispatcher.dispatched_ids == [event.id]


async def test_dead_letters_after_max_attempts(db_session):
    event = _make_event()
    db_session.add(event)
    await db_session.commit()

    dispatcher = RecordingDispatcher()
    dispatcher.always_fail_ids.add(event.id)

    last_status = None
    for _ in range(MAX_ATTEMPTS):
        last_status = await process_next(db_session, dispatcher)
        await _force_available_now(db_session, event.id)

    assert last_status == "DEAD_LETTER"
    await db_session.refresh(event)
    assert event.attempt_count == MAX_ATTEMPTS
    assert event.status == "DEAD_LETTER"
    assert dispatcher.dispatched_ids == []

    # A dead-lettered event must never be picked up by normal polling again.
    processed = await run_batch(db_session, dispatcher)
    assert processed == 0


async def test_requeue_dead_letter_allows_manual_replay(db_session):
    event = _make_event()
    db_session.add(event)
    await db_session.commit()

    dispatcher = RecordingDispatcher()
    dispatcher.always_fail_ids.add(event.id)
    for _ in range(MAX_ATTEMPTS):
        await process_next(db_session, dispatcher)
        await _force_available_now(db_session, event.id)
    await db_session.refresh(event)
    assert event.status == "DEAD_LETTER"

    dispatcher.always_fail_ids.discard(event.id)
    requeued = await requeue_dead_letter(db_session, event.id)
    assert requeued is True

    await db_session.refresh(event)
    assert event.status == "PENDING"
    assert event.attempt_count == 0

    result = await process_next(db_session, dispatcher)
    assert result == "PROCESSED"
    assert dispatcher.dispatched_ids == [event.id]


async def test_requeue_dead_letter_is_a_no_op_for_non_dead_lettered_events(db_session):
    event = _make_event()
    db_session.add(event)
    await db_session.commit()

    result = await requeue_dead_letter(db_session, event.id)
    assert result is False


async def test_payment_api_outbox_events_are_processed_by_the_worker(
    api_client, merchant_with_key, db_sessionmaker
):
    """The Phase 3 payment API already writes outbox_events transactionally
    (docs/architecture.md section 10). This proves the worker built here
    consumes exactly those rows with zero changes to the producer."""
    merchant_id, api_key = merchant_with_key
    body = {
        "amount": 2500,
        "currency": "USD",
        "payment_method": {"type": "token", "token": "pm_demo_outbox_test"},
    }
    response = await api_client.post(
        "/v1/payments",
        json=body,
        headers={"Authorization": f"Bearer {api_key}", "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 201
    payment_id = response.json()["id"]

    async with db_sessionmaker() as session:
        dispatcher = RecordingDispatcher()
        processed = await run_batch(session, dispatcher)

        assert processed >= 2  # at least payment.created + payment.processing
        remaining_pending = (
            (await session.execute(select(OutboxEvent).where(OutboxEvent.status == "PENDING")))
            .scalars()
            .all()
        )
        assert remaining_pending == []

        events = (
            (
                await session.execute(
                    select(OutboxEvent).where(OutboxEvent.aggregate_id == uuid.UUID(payment_id))
                )
            )
            .scalars()
            .all()
        )
        event_types = {e.event_type for e in events}
        assert "payment.created" in event_types
        assert "payment.processing" in event_types
        assert all(e.status == "PROCESSED" for e in events)
