"""The brief's headline refund requirement (product brief sections 14-15):
10+ concurrent refund requests against the same payment must never let the
total refunded amount exceed the original payment -- enforced by locking
the payment row and reserving each refund's amount inside that lock
(packages/payments/service.py:refund_payment), not by an application-level
"read the sum, then decide" check that a race could slip through.
"""

import asyncio
import collections
import uuid

from database.models import PaymentIntent, Refund
from sqlalchemy import func, select

CONCURRENT_REFUNDS = 10
PAYMENT_AMOUNT = 10_000
REFUND_AMOUNT = 3_000  # floor(10000 / 3000) == 3 can succeed; the other 7 must be rejected


def _headers(api_key: str, idempotency_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Idempotency-Key": idempotency_key}


async def _create_succeeded_payment(api_client, api_key: str, amount: int) -> str:
    create = await api_client.post(
        "/v1/payments",
        json={
            "amount": amount,
            "currency": "USD",
            "payment_method": {"type": "token", "token": f"pm_demo_{uuid.uuid4().hex}"},
        },
        headers=_headers(api_key, str(uuid.uuid4())),
    )
    assert create.status_code == 201
    payment_id = create.json()["id"]

    capture = await api_client.post(
        f"/v1/payments/{payment_id}/capture", headers=_headers(api_key, str(uuid.uuid4()))
    )
    assert capture.status_code == 200
    return payment_id


async def test_concurrent_refunds_never_exceed_payment_amount(api_client, merchant_with_key, db_sessionmaker):
    merchant_id, api_key = merchant_with_key
    payment_id = await _create_succeeded_payment(api_client, api_key, PAYMENT_AMOUNT)

    responses = await asyncio.gather(
        *(
            api_client.post(
                f"/v1/payments/{payment_id}/refunds",
                json={"amount": REFUND_AMOUNT},
                headers=_headers(api_key, str(uuid.uuid4())),
            )
            for _ in range(CONCURRENT_REFUNDS)
        )
    )

    status_counts = collections.Counter(r.status_code for r in responses)
    assert status_counts[201] == 3, (
        f"expected exactly floor({PAYMENT_AMOUNT}/{REFUND_AMOUNT})=3 refunds to succeed, got {status_counts}"
    )
    assert status_counts[409] == CONCURRENT_REFUNDS - 3
    assert all(
        r.json()["error"]["code"] == "REFUND_EXCEEDS_PAYMENT" for r in responses if r.status_code == 409
    )

    async with db_sessionmaker() as session:
        total_refunded = (
            await session.execute(
                select(func.coalesce(func.sum(Refund.amount_minor), 0)).where(
                    Refund.payment_intent_id == uuid.UUID(payment_id), Refund.status == "SUCCEEDED"
                )
            )
        ).scalar_one()
        succeeded_refund_count = (
            await session.execute(
                select(func.count())
                .select_from(Refund)
                .where(Refund.payment_intent_id == uuid.UUID(payment_id), Refund.status == "SUCCEEDED")
            )
        ).scalar_one()

        assert total_refunded == 3 * REFUND_AMOUNT
        assert total_refunded <= PAYMENT_AMOUNT, (
            f"THE INVARIANT: total refunded ({total_refunded}) must never exceed the payment amount "
            f"({PAYMENT_AMOUNT}), regardless of how many requests raced for it"
        )
        assert succeeded_refund_count == 3


async def test_concurrent_identical_refund_requests_produce_exactly_one_refund(
    api_client, merchant_with_key, db_sessionmaker
):
    """Same scenario as the payment-creation and webhook concurrency tests,
    applied to refunds: N concurrent retries under the *same* Idempotency-Key
    must collapse to exactly one logical refund, not N."""
    merchant_id, api_key = merchant_with_key
    payment_id = await _create_succeeded_payment(api_client, api_key, PAYMENT_AMOUNT)
    idempotency_key = f"refund-key-{uuid.uuid4()}"

    responses = await asyncio.gather(
        *(
            api_client.post(
                f"/v1/payments/{payment_id}/refunds",
                json={"amount": 2000},
                headers=_headers(api_key, idempotency_key),
            )
            for _ in range(CONCURRENT_REFUNDS)
        )
    )

    status_counts = collections.Counter(r.status_code for r in responses)
    assert set(status_counts) <= {201, 409}
    created_ids = {r.json()["id"] for r in responses if r.status_code == 201}
    assert len(created_ids) == 1, (
        f"all successful responses must reference the same refund, got {created_ids}"
    )

    async with db_sessionmaker() as session:
        refund_count = (
            await session.execute(
                select(func.count())
                .select_from(Refund)
                .where(Refund.payment_intent_id == uuid.UUID(payment_id))
            )
        ).scalar_one()
        assert refund_count == 1, f"expected exactly 1 refund row, found {refund_count}"

        intent = await session.get(PaymentIntent, uuid.UUID(payment_id))
        assert intent.status == "SUCCEEDED"  # partial refund (2000 of 10000), not fully refunded
