"""Phase 14: the chaos/failure-simulator proof. Drives a batch of concurrent
payments through the real HTTP API with a ChaosProvider standing in for
app.state.provider, so a chunk of authorize() calls report UNKNOWN to the
caller for reasons that have nothing to do with what the merchant sent --
then runs the same reconciliation pass an operator would trigger, and
checks the invariants that actually matter: nothing gets lost, nothing
gets double-settled, and the books stay balanced, regardless of which
individual requests chaos decided to corrupt.
"""

import asyncio
import uuid

from database.models import PaymentAttempt, PaymentIntent, ProviderTransaction
from ledger.invariants import global_ledger_balance
from providers import ChaosConfig, ChaosProvider, MockProvider
from reconciliation import run_reconciliation_pass
from sqlalchemy import func, select

BATCH_SIZE = 30


def _headers(api_key: str, idempotency_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Idempotency-Key": idempotency_key}


async def test_chaos_burst_resolves_cleanly_under_reconciliation(
    api_client, merchant_with_key, db_sessionmaker, monkeypatch
):
    from apps.api.main import app

    # Phase 16's merchant-scoped rate limiter is a different concern from
    # what this test proves (resilience under chaos, not abuse prevention)
    # -- at the default capacity, BATCH_SIZE concurrent requests from one
    # merchant would only avoid 429s by luck of real per-request latency
    # leaving enough time for the bucket to refill mid-burst.
    monkeypatch.setenv("RATE_LIMIT_CAPACITY", str(BATCH_SIZE * 2))

    merchant_id, api_key = merchant_with_key
    original_provider = app.state.provider
    chaos = ChaosProvider(MockProvider(), ChaosConfig(unknown_rate=0.4, seed=7))
    app.state.provider = chaos
    try:
        responses = await asyncio.gather(
            *(
                api_client.post(
                    "/v1/payments",
                    json={
                        "amount": 1000 + i,
                        "currency": "USD",
                        "payment_method": {"type": "token", "token": f"pm_demo_ok_{uuid.uuid4().hex}"},
                    },
                    headers=_headers(api_key, str(uuid.uuid4())),
                )
                for i in range(BATCH_SIZE)
            )
        )
        assert all(r.status_code == 201 for r in responses), [r.status_code for r in responses]
        payment_ids = [r.json()["id"] for r in responses]
        initial_status_by_id = {r.json()["id"]: r.json()["status"] for r in responses}
        corrupted_ids = {pid for pid, status in initial_status_by_id.items() if status == "UNKNOWN"}
        # A 40% corruption rate on 30 independent requests should produce at
        # least one UNKNOWN -- if not, this run is not actually exercising
        # chaos and the test would be silently vacuous.
        assert corrupted_ids

        async with db_sessionmaker() as session:
            await run_reconciliation_pass(session, chaos, merchant_id=merchant_id)

        async with db_sessionmaker() as session:
            rows = (
                await session.execute(
                    select(PaymentIntent.status, func.count())
                    .where(PaymentIntent.id.in_([uuid.UUID(p) for p in payment_ids]))
                    .group_by(PaymentIntent.status)
                )
            ).all()
            final_statuses = dict(rows)

            # Every chaos-corrupted payment must have resolved to a real
            # terminal status -- reconciliation must never leave a payment
            # sitting in UNKNOWN when the provider actually knows the truth
            # (MockProvider always does, here). A payment chaos left alone
            # correctly stays PROCESSING: a successful authorize() is only
            # "authorized, awaiting capture" in this system (docs/payments.md)
            # -- this test never calls capture, so PROCESSING is the correct
            # resting state for it, not a sign anything is stuck.
            assert "UNKNOWN" not in final_statuses, final_statuses
            assert set(final_statuses) <= {"PROCESSING", "SUCCEEDED", "FAILED"}
            assert sum(final_statuses.values()) == BATCH_SIZE

            # Precisely: every payment chaos corrupted must have been
            # resolved by reconciliation to SUCCEEDED specifically (every
            # token used here has a true outcome of SUCCEEDED) -- not just
            # "some non-UNKNOWN status".
            statuses_now = dict(
                (
                    await session.execute(
                        select(PaymentIntent.id, PaymentIntent.status).where(
                            PaymentIntent.id.in_([uuid.UUID(p) for p in payment_ids])
                        )
                    )
                ).all()
            )
            for payment_id in payment_ids:
                expected = "SUCCEEDED" if payment_id in corrupted_ids else "PROCESSING"
                assert statuses_now[uuid.UUID(payment_id)] == expected, (payment_id, statuses_now)

            # Every payment has exactly the attempts its own history
            # explains: one from create_payment() for a payment chaos left
            # alone, or two for a payment chaos corrupted (the original
            # UNKNOWN attempt, plus the one reconciliation adds when it
            # backfills the real outcome) -- never zero, and never an
            # unexplained extra from reconciliation double-processing.
            attempt_counts = dict(
                (
                    await session.execute(
                        select(PaymentAttempt.payment_intent_id, func.count())
                        .where(PaymentAttempt.payment_intent_id.in_([uuid.UUID(p) for p in payment_ids]))
                        .group_by(PaymentAttempt.payment_intent_id)
                    )
                ).all()
            )
            assert len(attempt_counts) == BATCH_SIZE
            for payment_id in payment_ids:
                expected = 2 if payment_id in corrupted_ids else 1
                assert attempt_counts[uuid.UUID(payment_id)] == expected, (payment_id, attempt_counts)

            # Every reconciliation-resolved payment must carry exactly one
            # provider transaction record, backfilled by reconciliation's
            # SUCCEEDED path -- never zero, never two.
            corrupted_uuids = [uuid.UUID(p) for p in corrupted_ids]
            txn_counts = dict(
                (
                    await session.execute(
                        select(PaymentAttempt.payment_intent_id, func.count())
                        .select_from(ProviderTransaction)
                        .join(PaymentAttempt, ProviderTransaction.payment_attempt_id == PaymentAttempt.id)
                        .where(PaymentAttempt.payment_intent_id.in_(corrupted_uuids))
                        .group_by(PaymentAttempt.payment_intent_id)
                    )
                ).all()
            )
            assert len(txn_counts) == len(corrupted_uuids)
            assert all(count == 1 for count in txn_counts.values()), txn_counts

            # The ledger stays balanced no matter how much of this batch
            # went through the reconciliation path instead of the direct
            # create_payment() success path.
            total_debits, total_credits = await global_ledger_balance(session)
            assert total_debits == total_credits
    finally:
        app.state.provider = original_provider
