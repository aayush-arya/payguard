"""The brief's headline demo, proven at the actual HTTP boundary (not just
the service layer already covered by tests/concurrency/test_idempotency_race.py
in Phase 2): 100 concurrent POST /v1/payments requests carrying the same
Idempotency-Key must produce 100 HTTP responses but exactly one payment
record and exactly one provider authorization -- verified by querying the
database afterward, never by trusting that the responses merely "looked
successful".
"""

import asyncio
import collections
import uuid

from database.models import PaymentAttempt, PaymentIntent
from sqlalchemy import func, select

CONCURRENCY = 100


def _headers(api_key: str, idempotency_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Idempotency-Key": idempotency_key}


async def test_100_concurrent_identical_payment_requests_yield_one_payment(
    api_client, merchant_with_key, db_sessionmaker
):
    merchant_id, api_key = merchant_with_key
    idempotency_key = f"key-{uuid.uuid4()}"
    body = {
        "amount": 4999,
        "currency": "USD",
        "merchant_reference": "order_race",
        "payment_method": {"type": "token", "token": "pm_demo_race"},
    }

    responses = await asyncio.gather(
        *(
            api_client.post("/v1/payments", json=body, headers=_headers(api_key, idempotency_key))
            for _ in range(CONCURRENCY)
        )
    )

    status_counts = collections.Counter(r.status_code for r in responses)
    # Every response must be a well-formed, safe outcome: the winner's 201,
    # a replay of that same 201 once it exists, or a 409 for a caller that
    # hit IN_PROGRESS during the brief window before the winner completes.
    assert set(status_counts) <= {201, 409}, f"unexpected status codes: {status_counts}"

    created_bodies = {r.json()["id"] for r in responses if r.status_code == 201}
    assert len(created_bodies) == 1, (
        f"all 201 responses must reference the same payment id, got {created_bodies}"
    )

    async with db_sessionmaker() as session:
        payment_count = (
            await session.execute(
                select(func.count())
                .select_from(PaymentIntent)
                .where(PaymentIntent.merchant_id == merchant_id)
            )
        ).scalar_one()
        attempt_count = (await session.execute(select(func.count()).select_from(PaymentAttempt))).scalar_one()

    assert payment_count == 1, f"expected exactly 1 payment_intents row, found {payment_count}"
    assert attempt_count == 1, (
        f"expected exactly 1 payment_attempts row (one provider authorization), found {attempt_count}"
    )


async def test_100_concurrent_requests_mixed_payloads_reject_the_losing_fingerprint(
    api_client, merchant_with_key, db_sessionmaker
):
    merchant_id, api_key = merchant_with_key
    idempotency_key = f"key-{uuid.uuid4()}"

    def _body(i: int) -> dict:
        amount = 1000 if i % 2 == 0 else 5000
        return {
            "amount": amount,
            "currency": "USD",
            "payment_method": {"type": "token", "token": "pm_demo_mixed"},
        }

    responses = await asyncio.gather(
        *(
            api_client.post("/v1/payments", json=_body(i), headers=_headers(api_key, idempotency_key))
            for i in range(CONCURRENCY)
        )
    )

    status_counts = collections.Counter(r.status_code for r in responses)
    assert set(status_counts) <= {201, 409}, f"unexpected status codes: {status_counts}"

    error_codes = collections.Counter(r.json()["error"]["code"] for r in responses if r.status_code == 409)
    # Only the losing fingerprint's callers can ever see IDEMPOTENCY_KEY_REUSED
    # -- the winning fingerprint's callers see either 201 or REQUEST_IN_PROGRESS,
    # never a conflict against their own (matching) fingerprint.
    assert 0 < error_codes["IDEMPOTENCY_KEY_REUSED"] <= CONCURRENCY // 2, (
        f"expected the losing-fingerprint half to be rejected as conflicts, got {error_codes}"
    )
    assert (
        status_counts[201] + error_codes["IDEMPOTENCY_KEY_REUSED"] + error_codes["REQUEST_IN_PROGRESS"]
        == CONCURRENCY
    )

    async with db_sessionmaker() as session:
        payment_count = (
            await session.execute(
                select(func.count())
                .select_from(PaymentIntent)
                .where(PaymentIntent.merchant_id == merchant_id)
            )
        ).scalar_one()
    assert payment_count == 1
