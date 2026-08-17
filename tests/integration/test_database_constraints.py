"""Integration tests proving the database-level constraints from
docs/architecture.md section 7 are actually enforced by Postgres, not just
assumed from the model definitions. Each test bypasses application logic and
inserts directly, so a constraint that silently isn't wired up cannot hide
behind service-layer validation."""

import uuid

import pytest
from database.models import (
    IdempotencyKey,
    LedgerEntry,
    PaymentIntent,
    ProviderTransaction,
    Refund,
    WebhookEvent,
)
from sqlalchemy.exc import DBAPIError, IntegrityError


async def _make_payment_intent(session, merchant_id, **overrides):
    defaults = dict(
        merchant_id=merchant_id,
        amount_minor=4999,
        currency="USD",
        status="CREATED",
    )
    defaults.update(overrides)
    intent = PaymentIntent(**defaults)
    session.add(intent)
    await session.flush()
    return intent


async def test_idempotency_key_unique_per_merchant(db_session, merchant_id):
    key1 = IdempotencyKey(
        merchant_id=merchant_id,
        idempotency_key="dup-key",
        request_fingerprint="fp1",
        status="PENDING",
    )
    db_session.add(key1)
    await db_session.commit()

    key2 = IdempotencyKey(
        merchant_id=merchant_id,
        idempotency_key="dup-key",
        request_fingerprint="fp2",
        status="PENDING",
    )
    db_session.add(key2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_idempotency_key_same_string_different_merchant_is_allowed(db_session, merchant_id):
    from database.models import Merchant

    other_merchant = Merchant(name="Other Merchant", api_key_hash="hash_" + uuid.uuid4().hex)
    db_session.add(other_merchant)
    await db_session.flush()

    db_session.add(
        IdempotencyKey(
            merchant_id=merchant_id, idempotency_key="shared-key", request_fingerprint="fp", status="PENDING"
        )
    )
    db_session.add(
        IdempotencyKey(
            merchant_id=other_merchant.id,
            idempotency_key="shared-key",
            request_fingerprint="fp",
            status="PENDING",
        )
    )
    await db_session.commit()  # must not raise


async def test_payment_intent_amount_must_be_positive(db_session, merchant_id):
    db_session.add(PaymentIntent(merchant_id=merchant_id, amount_minor=0, currency="USD", status="CREATED"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.parametrize("currency", ["usd", "US", "USDD", "12A"])
async def test_payment_intent_currency_must_be_iso4217_shaped(db_session, merchant_id, currency):
    db_session.add(
        PaymentIntent(merchant_id=merchant_id, amount_minor=100, currency=currency, status="CREATED")
    )
    # A too-long value is rejected by the VARCHAR(3) column type itself
    # before the CHECK constraint ever runs; everything else that isn't
    # three uppercase letters is rejected by the CHECK constraint
    # (IntegrityError). Both are the database refusing the row, just at
    # different layers -- DBAPIError is the common ancestor of both.
    with pytest.raises(DBAPIError):
        await db_session.commit()
    await db_session.rollback()


async def test_payment_intent_status_must_be_known_value(db_session, merchant_id):
    db_session.add(
        PaymentIntent(merchant_id=merchant_id, amount_minor=100, currency="USD", status="NOT_A_REAL_STATUS")
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_webhook_event_dedup_constraint(db_session):
    db_session.add(
        WebhookEvent(
            provider_name="mock",
            provider_event_id="evt_123",
            event_type="payment.succeeded",
            raw_payload={"foo": "bar"},
            signature="sig",
        )
    )
    await db_session.commit()

    db_session.add(
        WebhookEvent(
            provider_name="mock",
            provider_event_id="evt_123",
            event_type="payment.succeeded",
            raw_payload={"foo": "bar-resent"},
            signature="sig2",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_refund_amount_must_be_positive(db_session, merchant_id):
    intent = await _make_payment_intent(db_session, merchant_id, status="SUCCEEDED")
    db_session.add(Refund(payment_intent_id=intent.id, amount_minor=-10, status="PENDING"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_refund_status_must_be_known_value(db_session, merchant_id):
    intent = await _make_payment_intent(db_session, merchant_id, status="SUCCEEDED")
    db_session.add(Refund(payment_intent_id=intent.id, amount_minor=10, status="BOGUS"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_ledger_entry_direction_must_be_debit_or_credit(db_session, merchant_id):
    intent = await _make_payment_intent(db_session, merchant_id, status="SUCCEEDED")
    db_session.add(
        LedgerEntry(
            payment_intent_id=intent.id,
            ledger_transaction_id=uuid.uuid4(),
            account="Merchant Receivable",
            direction="SIDEWAYS",
            amount_minor=100,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_provider_transaction_id_unique_per_provider(db_session, merchant_id):
    intent = await _make_payment_intent(db_session, merchant_id, status="PROCESSING")
    from database.models import PaymentAttempt

    attempt1 = PaymentAttempt(
        payment_intent_id=intent.id, provider_name="mock", status="SUCCEEDED", attempt_number=1
    )
    attempt2 = PaymentAttempt(
        payment_intent_id=intent.id, provider_name="mock", status="SUCCEEDED", attempt_number=2
    )
    db_session.add_all([attempt1, attempt2])
    await db_session.flush()

    db_session.add(
        ProviderTransaction(
            payment_attempt_id=attempt1.id,
            provider_name="mock",
            provider_transaction_id="ptx_1",
            raw_status="ok",
            raw_response={},
        )
    )
    await db_session.commit()

    db_session.add(
        ProviderTransaction(
            payment_attempt_id=attempt2.id,
            provider_name="mock",
            provider_transaction_id="ptx_1",
            raw_status="ok",
            raw_response={},
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
