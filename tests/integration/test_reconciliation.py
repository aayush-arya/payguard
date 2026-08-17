"""Integration tests for reconciliation (Phase 10, ADR-008) against a real
Postgres database: resolving genuinely-unknown payment outcomes by asking
the provider directly (never guessing, never blindly retrying), including
the product brief's own Demo 3 scenario end to end."""

import uuid

from database.models import IdempotencyKey, LedgerEntry, PaymentEvent, PaymentIntent
from providers.base import ProviderOutcome, ProviderResult
from reconciliation import reconcile_payment, run_reconciliation_pass
from sqlalchemy import delete, select


def _headers(api_key: str, idempotency_key: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


async def _create_unknown_payment(api_client, api_key: str, token: str, amount: int = 5000) -> str:
    create = await api_client.post(
        "/v1/payments",
        json={"amount": amount, "currency": "USD", "payment_method": {"type": "token", "token": token}},
        headers=_headers(api_key, str(uuid.uuid4())),
    )
    assert create.status_code == 201
    assert create.json()["status"] == "UNKNOWN"
    return create.json()["id"]


class _StubProvider:
    """A minimal provider stub for testing reconciliation's comparison
    logic directly -- MockProvider always echoes back the amount/currency
    it was given, so there's no way to trigger a genuine mismatch through
    the normal authorize() flow."""

    name = "mock"

    def __init__(self, result: ProviderResult) -> None:
        self._result = result

    async def get_payment_status_by_idempotency_key(self, idempotency_key: str) -> ProviderResult:
        return self._result


async def test_reconciliation_resolves_timeout_to_succeeded_demo_3(
    api_client, merchant_with_key, db_sessionmaker
):
    """The product brief's Demo 3, verbatim: payment sent -> provider
    succeeds -> network timeout -> internal state UNKNOWN ->
    reconciliation -> SUCCEEDED."""
    from apps.api.main import app

    merchant_id, api_key = merchant_with_key
    payment_id = await _create_unknown_payment(
        api_client, api_key, f"pm_demo_timeout_{uuid.uuid4().hex}", amount=4999
    )

    async with db_sessionmaker() as session:
        report = await reconcile_payment(session, uuid.UUID(payment_id), merchant_id, app.state.provider)
    assert report.result == "RESOLVED_SUCCEEDED"

    async with db_sessionmaker() as session:
        intent = await session.get(PaymentIntent, uuid.UUID(payment_id))
        assert intent.status == "SUCCEEDED"

        # Resolving positive is a real settlement -- the ledger records it
        # exactly like a capture would (docs/reconciliation.md).
        entries = (
            (await session.execute(select(LedgerEntry).where(LedgerEntry.payment_intent_id == intent.id)))
            .scalars()
            .all()
        )
        assert len(entries) == 2
        assert {e.amount_minor for e in entries} == {4999}

        events = (
            (
                await session.execute(
                    select(PaymentEvent).where(
                        PaymentEvent.payment_intent_id == intent.id, PaymentEvent.actor == "RECONCILIATION"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1
        assert events[0].from_status == "UNKNOWN"
        assert events[0].to_status == "SUCCEEDED"


async def test_reconciliation_resolves_unknown_result_to_failed(
    api_client, merchant_with_key, db_sessionmaker
):
    from apps.api.main import app

    merchant_id, api_key = merchant_with_key
    payment_id = await _create_unknown_payment(
        api_client, api_key, f"pm_demo_unknown_result_{uuid.uuid4().hex}"
    )

    async with db_sessionmaker() as session:
        report = await reconcile_payment(session, uuid.UUID(payment_id), merchant_id, app.state.provider)
    assert report.result == "RESOLVED_FAILED"

    async with db_sessionmaker() as session:
        intent = await session.get(PaymentIntent, uuid.UUID(payment_id))
        assert intent.status == "FAILED"
        # A resolved-failed payment must not be recorded as a settlement.
        entries = (
            (await session.execute(select(LedgerEntry).where(LedgerEntry.payment_intent_id == intent.id)))
            .scalars()
            .all()
        )
        assert entries == []


async def test_reconciliation_reports_still_unknown_when_provider_cannot_answer(
    api_client, merchant_with_key, db_sessionmaker
):
    """Not every UNKNOWN resolves on the first pass -- the provider itself
    may not know yet. Reconciliation must say so honestly, not force an
    answer (ADR-008)."""
    from apps.api.main import app

    merchant_id, api_key = merchant_with_key
    payment_id = await _create_unknown_payment(
        api_client, api_key, f"pm_demo_still_unknown_{uuid.uuid4().hex}"
    )

    async with db_sessionmaker() as session:
        report = await reconcile_payment(session, uuid.UUID(payment_id), merchant_id, app.state.provider)
    assert report.result == "STILL_UNKNOWN"

    async with db_sessionmaker() as session:
        intent = await session.get(PaymentIntent, uuid.UUID(payment_id))
        assert intent.status == "UNKNOWN"


async def test_reconciliation_of_already_settled_payment_is_a_matched_noop(
    api_client, merchant_with_key, db_sessionmaker
):
    from apps.api.main import app

    merchant_id, api_key = merchant_with_key
    create = await api_client.post(
        "/v1/payments",
        json={
            "amount": 1000,
            "currency": "USD",
            "payment_method": {"type": "token", "token": f"pm_demo_{uuid.uuid4().hex}"},
        },
        headers=_headers(api_key, str(uuid.uuid4())),
    )
    payment_id = create.json()["id"]
    assert create.json()["status"] == "PROCESSING"

    async with db_sessionmaker() as session:
        report = await reconcile_payment(session, uuid.UUID(payment_id), merchant_id, app.state.provider)
    assert report.result == "MATCHED"

    async with db_sessionmaker() as session:
        intent = await session.get(PaymentIntent, uuid.UUID(payment_id))
        assert intent.status == "PROCESSING"  # untouched


async def test_reconciliation_reports_missing_internal_transaction_without_an_idempotency_key(
    api_client, merchant_with_key, db_sessionmaker
):
    from apps.api.main import app

    merchant_id, api_key = merchant_with_key
    payment_id = await _create_unknown_payment(api_client, api_key, f"pm_demo_timeout_{uuid.uuid4().hex}")

    async with db_sessionmaker() as session:
        await session.execute(
            delete(IdempotencyKey).where(IdempotencyKey.payment_intent_id == uuid.UUID(payment_id))
        )
        await session.commit()

    async with db_sessionmaker() as session:
        report = await reconcile_payment(session, uuid.UUID(payment_id), merchant_id, app.state.provider)
    assert report.result == "MISSING_INTERNAL_TRANSACTION"

    async with db_sessionmaker() as session:
        intent = await session.get(PaymentIntent, uuid.UUID(payment_id))
        assert intent.status == "UNKNOWN"  # left unresolved, not guessed at


async def test_reconciliation_flags_amount_mismatch_without_auto_correcting(
    api_client, merchant_with_key, db_sessionmaker
):
    merchant_id, api_key = merchant_with_key
    payment_id = await _create_unknown_payment(
        api_client, api_key, f"pm_demo_timeout_{uuid.uuid4().hex}", amount=5000
    )

    stub = _StubProvider(
        ProviderResult(
            outcome=ProviderOutcome.SUCCEEDED,
            provider_transaction_id="ptx_fake",
            raw_status="authorized",
            raw_response={"amount_minor": 9999, "currency": "USD"},
        )
    )

    async with db_sessionmaker() as session:
        report = await reconcile_payment(session, uuid.UUID(payment_id), merchant_id, stub)
    assert report.result == "AMOUNT_MISMATCH"

    async with db_sessionmaker() as session:
        intent = await session.get(PaymentIntent, uuid.UUID(payment_id))
        assert intent.status == "UNKNOWN"  # NOT auto-corrected to SUCCEEDED


async def test_reconciliation_flags_currency_mismatch_without_auto_correcting(
    api_client, merchant_with_key, db_sessionmaker
):
    merchant_id, api_key = merchant_with_key
    payment_id = await _create_unknown_payment(
        api_client, api_key, f"pm_demo_timeout_{uuid.uuid4().hex}", amount=5000
    )

    stub = _StubProvider(
        ProviderResult(
            outcome=ProviderOutcome.SUCCEEDED,
            provider_transaction_id="ptx_fake",
            raw_status="authorized",
            raw_response={"amount_minor": 5000, "currency": "EUR"},
        )
    )

    async with db_sessionmaker() as session:
        report = await reconcile_payment(session, uuid.UUID(payment_id), merchant_id, stub)
    assert report.result == "CURRENCY_MISMATCH"

    async with db_sessionmaker() as session:
        intent = await session.get(PaymentIntent, uuid.UUID(payment_id))
        assert intent.status == "UNKNOWN"


async def test_run_reconciliation_pass_resolves_every_unknown_payment(
    api_client, merchant_with_key, db_sessionmaker
):
    from apps.api.main import app

    merchant_id, api_key = merchant_with_key
    await _create_unknown_payment(api_client, api_key, f"pm_demo_timeout_{uuid.uuid4().hex}")
    await _create_unknown_payment(api_client, api_key, f"pm_demo_unknown_result_{uuid.uuid4().hex}")

    async with db_sessionmaker() as session:
        reports = await run_reconciliation_pass(session, app.state.provider)

    assert len(reports) == 2
    assert {r.result for r in reports} == {"RESOLVED_SUCCEEDED", "RESOLVED_FAILED"}

    async with db_sessionmaker() as session:
        remaining_unknown = (
            (await session.execute(select(PaymentIntent).where(PaymentIntent.status == "UNKNOWN")))
            .scalars()
            .all()
        )
    assert remaining_unknown == []
