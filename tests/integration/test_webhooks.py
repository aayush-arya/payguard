"""Integration tests for POST /v1/webhooks/provider against a real Postgres
database: signature/timestamp verification at the HTTP boundary, dedup on
(provider_name, provider_event_id), and the full receive -> outbox -> worker
-> applied-transition pipeline end to end."""

import json
import os
import time
import uuid

from database.models import PaymentIntent, ProviderTransaction, WebhookEvent
from outbox.dispatchers import WebhookEffectDispatcher
from outbox.worker import run_batch
from sqlalchemy import func, select
from webhooks.security import sign_payload


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
    """Creates a payment via the real API (ends PROCESSING/authorized) and returns its id."""
    body = {
        "amount": 3000,
        "currency": "USD",
        "payment_method": {"type": "token", "token": f"pm_demo_{uuid.uuid4().hex}"},
    }
    response = await api_client.post(
        "/v1/payments",
        json=body,
        headers={"Authorization": f"Bearer {api_key}", "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 201
    payment_id = response.json()["id"]
    assert response.json()["status"] == "PROCESSING"
    return payment_id


async def test_webhook_valid_signature_is_accepted(api_client):
    payload = {"id": f"evt_{uuid.uuid4()}", "type": "payment.succeeded", "data": {}}
    raw_body, headers = _signed_request(payload)
    response = await api_client.post("/v1/webhooks/provider", content=raw_body, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"received": True}


async def test_webhook_invalid_signature_is_rejected(api_client):
    payload = {"id": f"evt_{uuid.uuid4()}", "type": "payment.succeeded", "data": {}}
    raw_body = json.dumps(payload).encode()
    headers = {
        "X-PayGuard-Signature": "0" * 64,
        "X-PayGuard-Timestamp": str(int(time.time())),
    }
    response = await api_client.post("/v1/webhooks/provider", content=raw_body, headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "WEBHOOK_SIGNATURE_INVALID"


async def test_webhook_missing_headers_is_rejected(api_client):
    payload = {"id": f"evt_{uuid.uuid4()}", "type": "payment.succeeded", "data": {}}
    response = await api_client.post("/v1/webhooks/provider", json=payload)
    assert response.status_code == 401


async def test_webhook_dedup_second_delivery_is_acked_but_not_reprocessed(api_client, db_sessionmaker):
    event_id = f"evt_{uuid.uuid4()}"
    payload = {"id": event_id, "type": "payment.succeeded", "data": {}}
    raw_body, headers = _signed_request(payload)

    first = await api_client.post("/v1/webhooks/provider", content=raw_body, headers=headers)
    second = await api_client.post("/v1/webhooks/provider", content=raw_body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200  # ack both times -- never signal failure to the provider

    async with db_sessionmaker() as session:
        count = (
            await session.execute(
                select(func.count())
                .select_from(WebhookEvent)
                .where(WebhookEvent.provider_event_id == event_id)
            )
        ).scalar_one()
    assert count == 1, "a duplicate delivery must not create a second webhook_events row"


async def test_webhook_end_to_end_confirms_authorized_payment(api_client, merchant_with_key, db_sessionmaker):
    """The full pipeline: create a payment (ends PROCESSING/authorized),
    receive a payment.succeeded webhook referencing its provider transaction,
    let the outbox worker apply it, and confirm the payment lands SUCCEEDED --
    exactly like a real provider confirming async settlement without an
    explicit capture call."""
    _, api_key = merchant_with_key
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
    response = await api_client.post("/v1/webhooks/provider", content=raw_body, headers=headers)
    assert response.status_code == 200

    async with db_sessionmaker() as session:
        dispatcher = WebhookEffectDispatcher()
        processed = await run_batch(session, dispatcher)
        assert processed >= 1

        intent = await session.get(PaymentIntent, uuid.UUID(payment_id))
        assert intent.status == "SUCCEEDED"

        webhook_event = (
            await session.execute(select(WebhookEvent).where(WebhookEvent.provider_event_id == payload["id"]))
        ).scalar_one()
        assert webhook_event.processing_status == "PROCESSED"


async def test_webhook_for_unknown_provider_transaction_is_ignored_not_crashed(api_client, db_sessionmaker):
    payload = {
        "id": f"evt_{uuid.uuid4()}",
        "type": "payment.succeeded",
        "data": {"provider_transaction_id": "ptx_does_not_exist"},
    }
    raw_body, headers = _signed_request(payload)
    response = await api_client.post("/v1/webhooks/provider", content=raw_body, headers=headers)
    assert response.status_code == 200

    async with db_sessionmaker() as session:
        dispatcher = WebhookEffectDispatcher()
        processed = await run_batch(session, dispatcher)
        assert processed >= 1

        webhook_event = (
            await session.execute(select(WebhookEvent).where(WebhookEvent.provider_event_id == payload["id"]))
        ).scalar_one()
        assert webhook_event.processing_status == "IGNORED"


async def test_unrecognized_event_type_is_ignored_not_crashed(api_client, db_sessionmaker):
    payload = {"id": f"evt_{uuid.uuid4()}", "type": "refund.succeeded", "data": {}}
    raw_body, headers = _signed_request(payload)
    response = await api_client.post("/v1/webhooks/provider", content=raw_body, headers=headers)
    assert response.status_code == 200

    async with db_sessionmaker() as session:
        dispatcher = WebhookEffectDispatcher()
        await run_batch(session, dispatcher)

        webhook_event = (
            await session.execute(select(WebhookEvent).where(WebhookEvent.provider_event_id == payload["id"]))
        ).scalar_one()
        assert webhook_event.processing_status == "IGNORED"
