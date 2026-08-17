"""Two concurrency scenarios explicitly called out in the product brief:

1. Demo 4 -- a provider sending the same webhook 20 times must still produce
   exactly one logical state transition, not 20.
2. "simultaneous webhook + API request" -- a merchant's explicit capture call
   racing a provider's async confirmation webhook for the same payment must
   converge safely to one final state, with neither path corrupting the
   other or raising past the caller.
"""

import asyncio
import json
import os
import time
import uuid

from database.models import PaymentEvent, PaymentIntent, ProviderTransaction, WebhookEvent
from outbox.dispatchers import WebhookEffectDispatcher
from outbox.worker import run_batch
from sqlalchemy import func, select
from webhooks.security import sign_payload

DUPLICATE_DELIVERIES = 20


def _signed_request(payload: dict) -> tuple[bytes, dict]:
    raw_body = json.dumps(payload).encode()
    timestamp = str(int(time.time()))
    signature = sign_payload(os.environ["WEBHOOK_SECRET"], timestamp, raw_body)
    headers = {
        "X-PayGuard-Signature": signature,
        "X-PayGuard-Timestamp": timestamp,
        "Content-Type": "application/json",
    }
    return raw_body, headers


async def _create_authorized_payment(api_client, api_key: str) -> str:
    body = {
        "amount": 1500,
        "currency": "USD",
        "payment_method": {"type": "token", "token": f"pm_demo_{uuid.uuid4().hex}"},
    }
    response = await api_client.post(
        "/v1/payments",
        json=body,
        headers={"Authorization": f"Bearer {api_key}", "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_20_duplicate_webhook_deliveries_produce_one_logical_transition(
    api_client, merchant_with_key, db_sessionmaker
):
    _, api_key = merchant_with_key
    payment_id = await _create_authorized_payment(api_client, api_key)

    async with db_sessionmaker() as session:
        provider_transaction_id = (
            await session.execute(select(ProviderTransaction.provider_transaction_id))
        ).scalar_one()

    event_id = f"evt_{uuid.uuid4()}"
    payload = {
        "id": event_id,
        "type": "payment.succeeded",
        "data": {"provider_transaction_id": provider_transaction_id},
    }
    raw_body, headers = _signed_request(payload)

    responses = await asyncio.gather(
        *(
            api_client.post("/v1/webhooks/provider", content=raw_body, headers=headers)
            for _ in range(DUPLICATE_DELIVERIES)
        )
    )
    assert all(r.status_code == 200 for r in responses), "every delivery must be acked, even duplicates"

    async with db_sessionmaker() as session:
        webhook_event_count = (
            await session.execute(
                select(func.count())
                .select_from(WebhookEvent)
                .where(WebhookEvent.provider_event_id == event_id)
            )
        ).scalar_one()
        assert webhook_event_count == 1, "20 duplicate deliveries must dedup to exactly 1 webhook_events row"

        dispatcher = WebhookEffectDispatcher()
        await run_batch(session, dispatcher)

        intent = await session.get(PaymentIntent, uuid.UUID(payment_id))
        assert intent.status == "SUCCEEDED"

        transition_count = (
            await session.execute(
                select(func.count())
                .select_from(PaymentEvent)
                .where(
                    PaymentEvent.payment_intent_id == intent.id,
                    PaymentEvent.to_status == "SUCCEEDED",
                )
            )
        ).scalar_one()
        assert transition_count == 1, (
            f"expected exactly one logical PROCESSING->SUCCEEDED transition, found {transition_count}"
        )


async def test_concurrent_capture_and_webhook_converge_to_one_succeeded_state(
    api_client, merchant_with_key, db_sessionmaker
):
    merchant_id, api_key = merchant_with_key
    payment_id = await _create_authorized_payment(api_client, api_key)

    async with db_sessionmaker() as session:
        provider_transaction_id = (
            await session.execute(select(ProviderTransaction.provider_transaction_id))
        ).scalar_one()

    payload = {
        "id": f"evt_{uuid.uuid4()}",
        "type": "payment.succeeded",
        "data": {"provider_transaction_id": provider_transaction_id},
    }
    raw_body, headers = _signed_request(payload)
    webhook_response = await api_client.post("/v1/webhooks/provider", content=raw_body, headers=headers)
    assert webhook_response.status_code == 200

    async def _capture() -> int:
        response = await api_client.post(
            f"/v1/payments/{payment_id}/capture",
            headers={"Authorization": f"Bearer {api_key}", "Idempotency-Key": str(uuid.uuid4())},
        )
        return response.status_code

    async def _process_webhook_effect() -> None:
        async with db_sessionmaker() as session:
            dispatcher = WebhookEffectDispatcher()
            await run_batch(session, dispatcher)

    capture_status, _ = await asyncio.gather(_capture(), _process_webhook_effect())

    assert capture_status == 200

    async with db_sessionmaker() as session:
        intent = await session.get(PaymentIntent, uuid.UUID(payment_id))
        assert intent.status == "SUCCEEDED"

        transition_count = (
            await session.execute(
                select(func.count())
                .select_from(PaymentEvent)
                .where(
                    PaymentEvent.payment_intent_id == intent.id,
                    PaymentEvent.to_status == "SUCCEEDED",
                )
            )
        ).scalar_one()
        assert transition_count == 1, (
            "whichever path (capture or webhook) wins the race, the loser must "
            f"observe already-SUCCEEDED and no-op -- found {transition_count} transitions"
        )
