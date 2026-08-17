"""Integration tests for the idempotency claim/replay protocol (ADR-001)
against a real Postgres database -- these exercise the actual
INSERT ... ON CONFLICT DO NOTHING path and the reclaim UPDATE, not a mock."""

from datetime import UTC, datetime, timedelta

from database.models import IdempotencyKey
from idempotency.service import (
    ClaimOutcome,
    claim_idempotency_key,
    complete_idempotency_key,
    compute_fingerprint,
    fail_idempotency_key,
)
from sqlalchemy import update


def test_fingerprint_is_stable_for_identical_requests():
    fp1 = compute_fingerprint("POST", "/v1/payments", b'{"amount":100}')
    fp2 = compute_fingerprint("POST", "/v1/payments", b'{"amount":100}')
    assert fp1 == fp2


def test_fingerprint_differs_for_different_bodies():
    fp1 = compute_fingerprint("POST", "/v1/payments", b'{"amount":100}')
    fp2 = compute_fingerprint("POST", "/v1/payments", b'{"amount":500}')
    assert fp1 != fp2


async def test_first_claim_wins(db_session, merchant_id):
    result = await claim_idempotency_key(
        db_session, merchant_id=merchant_id, idempotency_key="k1", request_fingerprint="fp"
    )
    await db_session.commit()
    assert result.outcome == ClaimOutcome.CLAIMED
    assert result.key_row.status == "PENDING"


async def test_second_claim_with_same_fingerprint_while_pending_is_in_progress(db_session, merchant_id):
    first = await claim_idempotency_key(
        db_session, merchant_id=merchant_id, idempotency_key="k2", request_fingerprint="fp"
    )
    await db_session.commit()
    assert first.outcome == ClaimOutcome.CLAIMED

    second = await claim_idempotency_key(
        db_session, merchant_id=merchant_id, idempotency_key="k2", request_fingerprint="fp"
    )
    assert second.outcome == ClaimOutcome.IN_PROGRESS


async def test_claim_with_different_fingerprint_conflicts(db_session, merchant_id):
    first = await claim_idempotency_key(
        db_session, merchant_id=merchant_id, idempotency_key="k3", request_fingerprint="fp-a"
    )
    await db_session.commit()
    assert first.outcome == ClaimOutcome.CLAIMED

    second = await claim_idempotency_key(
        db_session, merchant_id=merchant_id, idempotency_key="k3", request_fingerprint="fp-b"
    )
    assert second.outcome == ClaimOutcome.CONFLICT


async def test_claim_after_completion_replays_stored_response(db_session, merchant_id):
    first = await claim_idempotency_key(
        db_session, merchant_id=merchant_id, idempotency_key="k4", request_fingerprint="fp"
    )
    await complete_idempotency_key(
        db_session,
        first.key_row,
        payment_intent_id=None,
        response_status=201,
        response_body={"id": "pay_123", "status": "PROCESSING"},
    )
    await db_session.commit()

    second = await claim_idempotency_key(
        db_session, merchant_id=merchant_id, idempotency_key="k4", request_fingerprint="fp"
    )
    assert second.outcome == ClaimOutcome.REPLAY
    assert second.key_row.response_status == 201
    assert second.key_row.response_body == {"id": "pay_123", "status": "PROCESSING"}


async def test_replay_rejects_mismatched_fingerprint_even_after_completion(db_session, merchant_id):
    first = await claim_idempotency_key(
        db_session, merchant_id=merchant_id, idempotency_key="k5", request_fingerprint="fp-original"
    )
    await complete_idempotency_key(
        db_session, first.key_row, payment_intent_id=None, response_status=201, response_body={}
    )
    await db_session.commit()

    second = await claim_idempotency_key(
        db_session, merchant_id=merchant_id, idempotency_key="k5", request_fingerprint="fp-mutated"
    )
    assert second.outcome == ClaimOutcome.CONFLICT


async def test_stale_pending_claim_is_reclaimed(db_session, merchant_id):
    first = await claim_idempotency_key(
        db_session, merchant_id=merchant_id, idempotency_key="k6", request_fingerprint="fp"
    )
    await db_session.commit()

    # Simulate a process that claimed the key and then crashed before it
    # could complete: push locked_at into the past.
    await db_session.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.id == first.key_row.id)
        .values(locked_at=datetime.now(UTC) - timedelta(hours=1))
    )
    await db_session.commit()

    second = await claim_idempotency_key(
        db_session,
        merchant_id=merchant_id,
        idempotency_key="k6",
        request_fingerprint="fp",
        stale_after=timedelta(seconds=30),
    )
    assert second.outcome == ClaimOutcome.CLAIMED


async def test_failed_claim_is_reclaimed_on_retry_with_same_fingerprint(db_session, merchant_id):
    first = await claim_idempotency_key(
        db_session, merchant_id=merchant_id, idempotency_key="k7", request_fingerprint="fp"
    )
    await fail_idempotency_key(db_session, first.key_row)
    await db_session.commit()

    second = await claim_idempotency_key(
        db_session, merchant_id=merchant_id, idempotency_key="k7", request_fingerprint="fp"
    )
    assert second.outcome == ClaimOutcome.CLAIMED
    assert second.key_row.status == "PENDING"
