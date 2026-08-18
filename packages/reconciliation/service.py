"""Reconciliation engine (ADR-008): resolving payments whose outcome we
genuinely don't know by asking the provider directly, rather than guessing
or blindly retrying (ADR-005).

Scope note: ADR-008 originally sketched reconciling both UNKNOWN payments
and payments "stuck in PROCESSING past an expected SLA window." Phase 3
settled on `PROCESSING` meaning "authorized, awaiting an explicit capture
call" (docs/payments.md) -- a legitimately long-lived, expected state, not a
stuck one. Reconciling stale PROCESSING payments would therefore be
reconciling against a false premise. This module is scoped to UNKNOWN only;
see docs/reconciliation.md for the full writeup.

Every reconcile_payment() call writes exactly one immutable
ReconciliationReport row, whatever the outcome -- including "nothing to do"
(already resolved) and "couldn't even ask" (no idempotency key on record).
"""

from __future__ import annotations

import uuid

from database.models import (
    IdempotencyKey,
    PaymentAttempt,
    PaymentIntent,
    ProviderTransaction,
    ReconciliationReport,
)
from domain.errors import PayGuardError
from domain.state_machine import Actor, PaymentStatus
from ledger.service import record_payment_settled
from observability import get_tracer, payment_id_var, reconciliation_mismatches_total
from payments.service import apply_transition, lock_payment
from providers.base import PaymentProvider, ProviderOutcome
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

_tracer = get_tracer("payguard.reconciliation")


async def find_payments_needing_reconciliation(session: AsyncSession) -> list[PaymentIntent]:
    stmt = select(PaymentIntent).where(PaymentIntent.status == PaymentStatus.UNKNOWN.value)
    return list((await session.execute(stmt)).scalars().all())


async def _original_idempotency_key(session: AsyncSession, payment_intent_id: uuid.UUID) -> str | None:
    """The key used for the *original* creation call -- the one whose
    authorize() response was lost. A payment can accumulate several
    idempotency_keys rows over its life (creation, capture, each refund);
    the earliest one by creation time is always the create_payment claim."""
    stmt = (
        select(IdempotencyKey.idempotency_key)
        .where(IdempotencyKey.payment_intent_id == payment_intent_id)
        .order_by(IdempotencyKey.created_at.asc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _next_attempt_number(session: AsyncSession, payment_intent_id: uuid.UUID) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(PaymentAttempt)
            .where(PaymentAttempt.payment_intent_id == payment_intent_id)
        )
    ).scalar_one() + 1


async def _write_report(
    session: AsyncSession,
    *,
    payment_intent_id: uuid.UUID,
    result: str,
    internal_status: str,
    provider_status: str | None,
    details: dict,
) -> ReconciliationReport:
    report = ReconciliationReport(
        payment_intent_id=payment_intent_id,
        result=result,
        internal_status=internal_status,
        provider_status=provider_status,
        details=details,
    )
    session.add(report)
    await session.commit()
    return report


async def reconcile_payment(
    session: AsyncSession, payment_id: uuid.UUID, merchant_id: uuid.UUID, provider: PaymentProvider
) -> ReconciliationReport:
    intent = await lock_payment(session, payment_id, merchant_id)
    if intent is None:
        raise PayGuardError("PAYMENT_NOT_FOUND", f"No payment found with id {payment_id}.")
    payment_id_var.set(str(intent.id))

    if intent.status != PaymentStatus.UNKNOWN.value:
        # Already resolved -- by a prior reconciliation pass, or by the
        # payment settling through another path entirely while this one was
        # queued. Report it and move on rather than re-asking the provider.
        await session.commit()
        return await _write_report(
            session,
            payment_intent_id=intent.id,
            result="MATCHED",
            internal_status=intent.status,
            provider_status=None,
            details={"note": "payment was not in UNKNOWN status at reconciliation time"},
        )

    idem_key = await _original_idempotency_key(session, intent.id)
    await session.commit()  # release the lock before the (slow, external) provider call

    if idem_key is None:
        return await _write_report(
            session,
            payment_intent_id=intent.id,
            result="MISSING_INTERNAL_TRANSACTION",
            internal_status="UNKNOWN",
            provider_status=None,
            details={"note": "no idempotency key on record to ask the provider about"},
        )

    with _tracer.start_as_current_span("provider.get_payment_status_by_idempotency_key"):
        provider_result = await provider.get_payment_status_by_idempotency_key(idem_key)

    # Re-lock to apply the result. Someone else (another reconciliation pass,
    # a webhook) may have resolved this payment while we were asking the
    # provider -- re-check under the fresh lock rather than trusting the
    # status we read before releasing it.
    intent = await lock_payment(session, payment_id, merchant_id)
    assert intent is not None
    if intent.status != PaymentStatus.UNKNOWN.value:
        await session.commit()
        return await _write_report(
            session,
            payment_intent_id=intent.id,
            result="MATCHED",
            internal_status=intent.status,
            provider_status=provider_result.raw_status,
            details={"note": "resolved by another path while awaiting the provider's answer"},
        )

    if provider_result.outcome is ProviderOutcome.UNKNOWN:
        await apply_transition(
            session, intent, PaymentStatus.UNKNOWN, Actor.RECONCILIATION, "reconciliation.still_unknown"
        )
        await session.commit()
        return await _write_report(
            session,
            payment_intent_id=intent.id,
            result="STILL_UNKNOWN",
            internal_status="UNKNOWN",
            provider_status=provider_result.raw_status,
            details={},
        )

    # The provider has an answer. A real status-lookup response would
    # normally echo the amount/currency it processed -- check those before
    # trusting the outcome at face value. Flagged, never auto-corrected: a
    # financial discrepancy needs a human, not a silent "fix" (ADR-008).
    reported_amount = provider_result.raw_response.get("amount_minor")
    reported_currency = provider_result.raw_response.get("currency")
    if reported_amount is not None and reported_amount != intent.amount_minor:
        reconciliation_mismatches_total.labels(result="AMOUNT_MISMATCH").inc()
        await session.commit()
        return await _write_report(
            session,
            payment_intent_id=intent.id,
            result="AMOUNT_MISMATCH",
            internal_status="UNKNOWN",
            provider_status=provider_result.raw_status,
            details={"internal_amount_minor": intent.amount_minor, "provider_amount_minor": reported_amount},
        )
    if reported_currency is not None and reported_currency != intent.currency:
        reconciliation_mismatches_total.labels(result="CURRENCY_MISMATCH").inc()
        await session.commit()
        return await _write_report(
            session,
            payment_intent_id=intent.id,
            result="CURRENCY_MISMATCH",
            internal_status="UNKNOWN",
            provider_status=provider_result.raw_status,
            details={"internal_currency": intent.currency, "provider_currency": reported_currency},
        )

    attempt_number = await _next_attempt_number(session, intent.id)
    if provider_result.outcome is ProviderOutcome.SUCCEEDED:
        attempt = PaymentAttempt(
            payment_intent_id=intent.id,
            provider_name=provider.name,
            status=ProviderOutcome.SUCCEEDED.value,
            failure_classification=None,
            attempt_number=attempt_number,
        )
        session.add(attempt)
        await session.flush()
        if provider_result.provider_transaction_id is not None:
            session.add(
                ProviderTransaction(
                    payment_attempt_id=attempt.id,
                    provider_name=provider.name,
                    provider_transaction_id=provider_result.provider_transaction_id,
                    raw_status=provider_result.raw_status,
                    raw_response=provider_result.raw_response,
                )
            )
        await apply_transition(
            session,
            intent,
            PaymentStatus.SUCCEEDED,
            Actor.RECONCILIATION,
            "reconciliation.resolved_succeeded",
        )
        # UNKNOWN can only transition to SUCCEEDED, never to PROCESSING
        # (docs/reconciliation.md) -- there's no "authorized, awaiting
        # capture" leg to represent here, so resolving positive means fully
        # settled, same as a completed capture.
        await record_payment_settled(session, payment_intent_id=intent.id, amount_minor=intent.amount_minor)
        result = "RESOLVED_SUCCEEDED"
    else:
        classification = "PERMANENT" if provider_result.outcome is ProviderOutcome.DECLINED else "UNKNOWN"
        attempt = PaymentAttempt(
            payment_intent_id=intent.id,
            provider_name=provider.name,
            status=provider_result.outcome.value,
            failure_classification=classification,
            attempt_number=attempt_number,
        )
        session.add(attempt)
        await apply_transition(
            session, intent, PaymentStatus.FAILED, Actor.RECONCILIATION, "reconciliation.resolved_failed"
        )
        result = "RESOLVED_FAILED"

    await session.commit()
    return await _write_report(
        session,
        payment_intent_id=intent.id,
        result=result,
        internal_status="UNKNOWN",
        provider_status=provider_result.raw_status,
        details={"provider_transaction_id": provider_result.provider_transaction_id},
    )


async def run_reconciliation_pass(
    session: AsyncSession, provider: PaymentProvider
) -> list[ReconciliationReport]:
    payments = await find_payments_needing_reconciliation(session)
    reports = []
    for intent in payments:
        report = await reconcile_payment(session, intent.id, intent.merchant_id, provider)
        reports.append(report)
    return reports
