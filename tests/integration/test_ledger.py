"""Integration tests for the double-entry ledger (Phase 9) against a real
Postgres database: entries written on real settlement events (capture,
webhook-confirmed settlement, refund), the global balance invariant holding
across a realistic sequence of operations, and the DB-level immutability
trigger actually blocking mutation."""

import json
import os
import time
import uuid

import pytest
from database.models import LedgerEntry
from ledger.invariants import find_unbalanced_ledger_transactions, global_ledger_balance
from ledger.service import MERCHANT_RECEIVABLE, PAYMENT_CLEARING, REFUND_LIABILITY
from outbox.dispatchers import WebhookEffectDispatcher
from outbox.worker import run_batch
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from webhooks.security import sign_payload


def _headers(api_key: str, idempotency_key: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


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


async def test_capture_writes_balanced_ledger_entries(api_client, merchant_with_key, db_sessionmaker):
    _, api_key = merchant_with_key
    payment_id = await _create_succeeded_payment(api_client, api_key, 5000)

    async with db_sessionmaker() as session:
        entries = (
            (
                await session.execute(
                    select(LedgerEntry).where(LedgerEntry.payment_intent_id == uuid.UUID(payment_id))
                )
            )
            .scalars()
            .all()
        )

    assert len(entries) == 2
    by_direction = {e.direction: e for e in entries}
    assert by_direction["DEBIT"].account == MERCHANT_RECEIVABLE
    assert by_direction["CREDIT"].account == PAYMENT_CLEARING
    assert by_direction["DEBIT"].amount_minor == by_direction["CREDIT"].amount_minor == 5000
    assert by_direction["DEBIT"].ledger_transaction_id == by_direction["CREDIT"].ledger_transaction_id


async def test_capture_idempotent_replay_does_not_double_write_ledger(
    api_client, merchant_with_key, db_sessionmaker
):
    _, api_key = merchant_with_key
    payment_id = await _create_succeeded_payment(api_client, api_key, 5000)

    # Capture again (already SUCCEEDED) -- a safe no-op per docs/payments.md.
    second_capture = await api_client.post(
        f"/v1/payments/{payment_id}/capture", headers=_headers(api_key, str(uuid.uuid4()))
    )
    assert second_capture.status_code == 200

    async with db_sessionmaker() as session:
        count = (
            await session.execute(
                select(func.count())
                .select_from(LedgerEntry)
                .where(LedgerEntry.payment_intent_id == uuid.UUID(payment_id))
            )
        ).scalar_one()
    assert count == 2, "a no-op capture replay must not write additional ledger entries"


async def test_partial_refunds_write_ledger_entries_matching_the_100_30_20_50_example(
    api_client, merchant_with_key, db_sessionmaker
):
    """The product brief's own example: a $100 payment refunded $30, $20,
    then $50 -- fully consuming it. Verify the ledger records the payment
    settlement plus all three refund settlements, and stays globally
    balanced throughout."""
    _, api_key = merchant_with_key
    payment_id = await _create_succeeded_payment(api_client, api_key, 10000)

    for amount in (3000, 2000, 5000):
        response = await api_client.post(
            f"/v1/payments/{payment_id}/refunds",
            json={"amount": amount},
            headers=_headers(api_key, str(uuid.uuid4())),
        )
        assert response.status_code == 201

    async with db_sessionmaker() as session:
        entries = (
            (
                await session.execute(
                    select(LedgerEntry).where(LedgerEntry.payment_intent_id == uuid.UUID(payment_id))
                )
            )
            .scalars()
            .all()
        )

        refund_debits = [e for e in entries if e.account == REFUND_LIABILITY]
        assert sorted(e.amount_minor for e in refund_debits) == [2000, 3000, 5000]

        total_debits, total_credits = await global_ledger_balance(session)
        assert total_debits == total_credits
        unbalanced = await find_unbalanced_ledger_transactions(session)
        assert unbalanced == []


async def test_declined_refund_writes_no_ledger_entries(api_client, merchant_with_key, db_sessionmaker):
    _, api_key = merchant_with_key
    payment_id = await _create_succeeded_payment(api_client, api_key, 5000)

    response = await api_client.post(
        f"/v1/payments/{payment_id}/refunds",
        json={"amount": 1000},
        headers=_headers(api_key, f"refund-declined-{uuid.uuid4()}"),
    )
    assert response.status_code == 201
    assert response.json()["status"] == "FAILED"

    async with db_sessionmaker() as session:
        refund_entries = (
            await session.execute(
                select(func.count())
                .select_from(LedgerEntry)
                .where(LedgerEntry.account.in_((REFUND_LIABILITY,)))
            )
        ).scalar_one()
    assert refund_entries == 0, "a failed refund must not be recorded in the ledger"


async def test_webhook_confirmed_settlement_writes_ledger_entries(
    api_client, merchant_with_key, db_sessionmaker
):
    from database.models import ProviderTransaction

    _, api_key = merchant_with_key
    create = await api_client.post(
        "/v1/payments",
        json={
            "amount": 4200,
            "currency": "USD",
            "payment_method": {"type": "token", "token": f"pm_demo_{uuid.uuid4().hex}"},
        },
        headers=_headers(api_key, str(uuid.uuid4())),
    )
    payment_id = create.json()["id"]
    assert create.json()["status"] == "PROCESSING"  # authorized, not yet captured

    async with db_sessionmaker() as session:
        provider_transaction_id = (
            await session.execute(select(ProviderTransaction.provider_transaction_id))
        ).scalar_one()

    payload = {
        "id": f"evt_{uuid.uuid4()}",
        "type": "payment.succeeded",
        "data": {"provider_transaction_id": provider_transaction_id},
    }
    raw_body = json.dumps(payload).encode()
    timestamp = str(int(time.time()))
    signature = sign_payload(os.environ["WEBHOOK_SECRET"], timestamp, raw_body)
    webhook_response = await api_client.post(
        "/v1/webhooks/provider",
        content=raw_body,
        headers={"X-PayGuard-Signature": signature, "X-PayGuard-Timestamp": timestamp},
    )
    assert webhook_response.status_code == 200

    async with db_sessionmaker() as session:
        await run_batch(session, WebhookEffectDispatcher())

        entries = (
            (
                await session.execute(
                    select(LedgerEntry).where(LedgerEntry.payment_intent_id == uuid.UUID(payment_id))
                )
            )
            .scalars()
            .all()
        )
    assert len(entries) == 2
    assert {e.amount_minor for e in entries} == {4200}


async def test_ledger_entries_cannot_be_updated(api_client, merchant_with_key, db_session):
    _, api_key = merchant_with_key
    payment_id = await _create_succeeded_payment(api_client, api_key, 1000)

    entry = (
        await db_session.execute(
            select(LedgerEntry).where(LedgerEntry.payment_intent_id == uuid.UUID(payment_id)).limit(1)
        )
    ).scalar_one()

    entry.amount_minor = 999999
    with pytest.raises(DBAPIError, match="immutable"):
        await db_session.commit()
    await db_session.rollback()


async def test_ledger_entries_cannot_be_deleted(api_client, merchant_with_key, db_session):
    _, api_key = merchant_with_key
    payment_id = await _create_succeeded_payment(api_client, api_key, 1000)

    entry = (
        await db_session.execute(
            select(LedgerEntry).where(LedgerEntry.payment_intent_id == uuid.UUID(payment_id)).limit(1)
        )
    ).scalar_one()

    await db_session.delete(entry)
    with pytest.raises(DBAPIError, match="immutable"):
        await db_session.commit()
    await db_session.rollback()
