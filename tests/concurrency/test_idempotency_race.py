"""The core claim of this project: N concurrent requests carrying the same
Idempotency-Key must produce exactly one logical payment operation. These
tests don't just assert HTTP-shaped outcomes -- they open one real Postgres
connection per simulated request, run them genuinely concurrently via
asyncio.gather, and then inspect the database directly to prove only one
side effect (one payment_intents row) was ever created.

Phase 2 has not yet built the full payment-creation API (that is Phase 3/5),
so "the side effect" here is the same thing the real API will do inside the
winning claim's transaction: insert exactly one payment_intents row. The
claim mechanism being proven here (ADR-001, ADR-002) is identical regardless
of what the winner's transaction goes on to do.
"""

import asyncio
import collections
import uuid
from datetime import UTC, datetime, timedelta

from database.models import IdempotencyKey, PaymentIntent
from idempotency.service import (
    ClaimOutcome,
    claim_idempotency_key,
    complete_idempotency_key,
)
from sqlalchemy import func, select, update

CONCURRENCY = 100


async def _simulate_request(sessionmaker, merchant_id, idempotency_key, fingerprint) -> ClaimOutcome:
    async with sessionmaker() as session:
        result = await claim_idempotency_key(
            session,
            merchant_id=merchant_id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
        )
        if result.outcome is not ClaimOutcome.CLAIMED:
            await session.commit()
            return result.outcome

        # This is the "one provider charge, one payment record" side effect --
        # only the request that actually won the claim should ever reach here.
        intent = PaymentIntent(
            merchant_id=merchant_id,
            amount_minor=4999,
            currency="USD",
            status="CREATED",
        )
        session.add(intent)
        await session.flush()
        await complete_idempotency_key(
            session,
            result.key_row,
            payment_intent_id=intent.id,
            response_status=201,
            response_body={"id": str(intent.id), "status": "CREATED"},
        )
        await session.commit()
        return result.outcome


async def _payment_count(sessionmaker, merchant_id) -> int:
    async with sessionmaker() as session:
        stmt = select(func.count()).select_from(PaymentIntent).where(PaymentIntent.merchant_id == merchant_id)
        return (await session.execute(stmt)).scalar_one()


async def test_concurrent_identical_requests_produce_exactly_one_payment(db_sessionmaker, merchant_id):
    idempotency_key = f"key-{uuid.uuid4()}"
    fingerprint = "fp-identical"

    outcomes = await asyncio.gather(
        *(
            _simulate_request(db_sessionmaker, merchant_id, idempotency_key, fingerprint)
            for _ in range(CONCURRENCY)
        )
    )

    counts = collections.Counter(outcomes)
    assert counts[ClaimOutcome.CLAIMED] == 1, (
        f"expected exactly one winner across {CONCURRENCY} concurrent identical requests, "
        f"got {counts[ClaimOutcome.CLAIMED]}: {counts}"
    )
    # Every loser must have been told IN_PROGRESS or REPLAY -- never CLAIMED
    # again and never CONFLICT (the fingerprint was identical for all of them).
    assert counts[ClaimOutcome.CONFLICT] == 0
    assert counts[ClaimOutcome.IN_PROGRESS] + counts[ClaimOutcome.REPLAY] == CONCURRENCY - 1

    payment_count = await _payment_count(db_sessionmaker, merchant_id)
    async with db_sessionmaker() as session:
        key_count = (
            await session.execute(
                select(func.count())
                .select_from(IdempotencyKey)
                .where(
                    IdempotencyKey.merchant_id == merchant_id,
                    IdempotencyKey.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one()

    assert payment_count == 1, f"expected exactly 1 payment_intents row, found {payment_count}"
    assert key_count == 1, f"expected exactly 1 idempotency_keys row, found {key_count}"


async def test_concurrent_requests_same_key_mixed_payloads(db_sessionmaker, merchant_id):
    """Half the callers retry with the original payload, half retry with a
    mutated one under the same key (a client bug). Exactly one payment must
    still be created -- for the fingerprint that actually won the race --
    and every caller using the *other* fingerprint must be rejected, never
    silently merged into the winner's payment."""
    idempotency_key = f"key-{uuid.uuid4()}"
    fingerprint_a = "fp-original"
    fingerprint_b = "fp-mutated"

    fingerprints = [fingerprint_a if i % 2 == 0 else fingerprint_b for i in range(CONCURRENCY)]
    outcomes = await asyncio.gather(
        *(_simulate_request(db_sessionmaker, merchant_id, idempotency_key, fp) for fp in fingerprints)
    )

    counts = collections.Counter(outcomes)
    assert counts[ClaimOutcome.CLAIMED] == 1
    assert counts[ClaimOutcome.CONFLICT] == CONCURRENCY // 2, (
        "exactly the callers using the losing fingerprint must be rejected as a conflict"
    )

    assert await _payment_count(db_sessionmaker, merchant_id) == 1


async def test_concurrent_reclaim_of_stale_key_is_exclusive(db_sessionmaker, merchant_id):
    """A worker retry racing an API retry against the same abandoned
    (crashed) claim must still hand out exactly one CLAIMED outcome."""
    idempotency_key = f"key-{uuid.uuid4()}"
    fingerprint = "fp-stale"

    async with db_sessionmaker() as session:
        first = await claim_idempotency_key(
            session, merchant_id=merchant_id, idempotency_key=idempotency_key, request_fingerprint=fingerprint
        )
        await session.commit()
        await session.execute(
            update(IdempotencyKey)
            .where(IdempotencyKey.id == first.key_row.id)
            .values(locked_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await session.commit()

    outcomes = await asyncio.gather(
        *(
            _simulate_request(db_sessionmaker, merchant_id, idempotency_key, fingerprint)
            for _ in range(CONCURRENCY)
        )
    )

    counts = collections.Counter(outcomes)
    assert counts[ClaimOutcome.CLAIMED] == 1, (
        f"exactly one concurrent reclaimer of the stale key should win, got {counts}"
    )

    assert await _payment_count(db_sessionmaker, merchant_id) == 1
