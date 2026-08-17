"""Payment creation, lookup, and capture (Phase 3).

Design note on PROCESSING vs. a separate "authorized" status: the Phase 1
state machine (docs/architecture.md section 6) has no dedicated status for
"authorized, awaiting capture" -- only CREATED, PROCESSING, SUCCEEDED, etc.
Rather than add one (and touch the already-shipped Phase 2 schema), a
successful `authorize()` leaves the payment_intents row in PROCESSING: the
attempt record shows the authorization succeeded, but the payment itself
isn't finalized until an explicit `capture_payment()` call moves
PROCESSING -> SUCCEEDED. This is a legitimate reading of PROCESSING ("not yet
finalized") and matches the demo flow (create -> authorize -> capture ->
success) with zero schema changes. See docs/payments.md for the full
writeup and the tradeoff this implies.

Every mutating call here is fully synchronous end-to-end (the HTTP response
doesn't return until the provider call and resulting transition are both
done). The request lifecycle diagram in docs/architecture.md shows an
async-looking sequence, but that relies on the outbox worker (Phase 6) to
pick up work after an early response -- until that exists, doing it
synchronously is more honest than pretending to be async.
"""

from __future__ import annotations

import uuid

from database.models import (
    IdempotencyKey,
    OutboxEvent,
    PaymentAttempt,
    PaymentEvent,
    PaymentIntent,
    ProviderTransaction,
    Refund,
)
from domain.errors import PayGuardError
from domain.state_machine import Actor, PaymentStatus, validate_payment_transition
from idempotency.service import (
    ClaimOutcome,
    claim_idempotency_key,
    complete_idempotency_key,
    compute_fingerprint,
    fail_idempotency_key,
)
from ledger.service import record_payment_settled, record_refund_settled
from providers.base import AuthorizeRequest, PaymentProvider, ProviderOutcome
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

_FAILURE_CLASSIFICATION = {
    ProviderOutcome.DECLINED: "PERMANENT",
    ProviderOutcome.TEMPORARY_FAILURE: "TRANSIENT",
    ProviderOutcome.UNKNOWN: "UNKNOWN",
}


def serialize_payment(intent: PaymentIntent) -> dict:
    return {
        "id": str(intent.id),
        "status": intent.status,
        "amount": intent.amount_minor,
        "currency": intent.currency,
        "merchant_reference": intent.merchant_reference,
        "created_at": intent.created_at.isoformat(),
        "updated_at": intent.updated_at.isoformat(),
    }


async def lock_payment(
    session: AsyncSession, payment_id: uuid.UUID, merchant_id: uuid.UUID
) -> PaymentIntent | None:
    stmt = (
        select(PaymentIntent)
        .where(PaymentIntent.id == payment_id, PaymentIntent.merchant_id == merchant_id)
        .with_for_update()
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def apply_transition(
    session: AsyncSession,
    intent: PaymentIntent,
    to_status: PaymentStatus,
    actor: Actor,
    outbox_event_type: str,
) -> None:
    from_status = PaymentStatus(intent.status)
    validate_payment_transition(from_status, to_status, actor)
    intent.status = to_status.value
    intent.version += 1
    session.add(
        PaymentEvent(
            payment_intent_id=intent.id,
            from_status=from_status.value,
            to_status=to_status.value,
            actor=actor.value,
            event_metadata={},
        )
    )
    session.add(
        OutboxEvent(
            aggregate_type="payment_intent",
            aggregate_id=intent.id,
            event_type=outbox_event_type,
            payload={"payment_id": str(intent.id), "status": to_status.value},
        )
    )


async def _latest_successful_provider_transaction(
    session: AsyncSession, payment_intent_id: uuid.UUID
) -> ProviderTransaction | None:
    stmt = (
        select(ProviderTransaction)
        .join(PaymentAttempt, ProviderTransaction.payment_attempt_id == PaymentAttempt.id)
        .where(
            PaymentAttempt.payment_intent_id == payment_intent_id,
            PaymentAttempt.status == ProviderOutcome.SUCCEEDED.value,
        )
        .order_by(PaymentAttempt.attempt_number.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def serialize_refund(refund: Refund) -> dict:
    return {
        "id": str(refund.id),
        "payment_id": str(refund.payment_intent_id),
        "amount": refund.amount_minor,
        "status": refund.status,
        "created_at": refund.created_at.isoformat(),
    }


async def _fail_claim_and_raise(session: AsyncSession, key_row_id: uuid.UUID, exc: BaseException) -> None:
    await session.rollback()
    key_row = await session.get(IdempotencyKey, key_row_id)
    if key_row is not None and key_row.status == "PENDING":
        await fail_idempotency_key(session, key_row)
        await session.commit()
    raise exc


async def create_payment(
    session: AsyncSession,
    *,
    merchant_id: uuid.UUID,
    idempotency_key: str,
    raw_body: bytes,
    amount_minor: int,
    currency: str,
    merchant_reference: str | None,
    payment_token: str,
    provider: PaymentProvider,
) -> tuple[int, dict]:
    fingerprint = compute_fingerprint("POST", "/v1/payments", raw_body)
    claim = await claim_idempotency_key(
        session, merchant_id=merchant_id, idempotency_key=idempotency_key, request_fingerprint=fingerprint
    )

    if claim.outcome is ClaimOutcome.CONFLICT:
        await session.commit()
        raise PayGuardError(
            "IDEMPOTENCY_KEY_REUSED", "This idempotency key was previously used with a different request."
        )
    if claim.outcome is ClaimOutcome.IN_PROGRESS:
        await session.commit()
        raise PayGuardError(
            "REQUEST_IN_PROGRESS", "A request with this idempotency key is already being processed."
        )
    if claim.outcome is ClaimOutcome.REPLAY:
        await session.commit()
        return claim.key_row.response_status, claim.key_row.response_body

    key_row_id = claim.key_row.id
    try:
        intent = PaymentIntent(
            merchant_id=merchant_id,
            amount_minor=amount_minor,
            currency=currency,
            merchant_reference=merchant_reference,
            status=PaymentStatus.CREATED.value,
        )
        session.add(intent)
        await session.flush()
        session.add(
            PaymentEvent(
                payment_intent_id=intent.id,
                from_status=None,
                to_status=PaymentStatus.CREATED.value,
                actor=Actor.API.value,
                event_metadata={},
            )
        )
        session.add(
            OutboxEvent(
                aggregate_type="payment_intent",
                aggregate_id=intent.id,
                event_type="payment.created",
                payload={"payment_id": str(intent.id)},
            )
        )
        await session.commit()

        # Fresh row lock before the provider call; released again before it
        # (docs/architecture.md section 8 -- never hold a DB lock across a
        # network call).
        intent = await lock_payment(session, intent.id, merchant_id)
        assert intent is not None
        await apply_transition(session, intent, PaymentStatus.PROCESSING, Actor.API, "payment.processing")
        await session.commit()

        result = await provider.authorize(
            AuthorizeRequest(
                amount_minor=amount_minor,
                currency=currency,
                token=payment_token,
                idempotency_key=idempotency_key,
            )
        )

        intent = await lock_payment(session, intent.id, merchant_id)
        assert intent is not None

        attempt_number = (
            await session.execute(
                select(func.count())
                .select_from(PaymentAttempt)
                .where(PaymentAttempt.payment_intent_id == intent.id)
            )
        ).scalar_one() + 1
        attempt = PaymentAttempt(
            payment_intent_id=intent.id,
            provider_name=provider.name,
            status=result.outcome.value,
            failure_classification=_FAILURE_CLASSIFICATION.get(result.outcome),
            attempt_number=attempt_number,
        )
        session.add(attempt)
        await session.flush()
        if result.provider_transaction_id is not None:
            session.add(
                ProviderTransaction(
                    payment_attempt_id=attempt.id,
                    provider_name=provider.name,
                    provider_transaction_id=result.provider_transaction_id,
                    raw_status=result.raw_status,
                    raw_response=result.raw_response,
                )
            )

        # DECLINED is terminal. TEMPORARY_FAILURE and UNKNOWN are
        # deliberately NOT auto-resolved here -- a retry engine (Phase 6/11)
        # and reconciliation (ADR-008) own those respectively, never a
        # blind inline retry (ADR-005). SUCCEEDED means "authorized"; the
        # payment stays PROCESSING until capture_payment() finalizes it.
        if result.outcome is ProviderOutcome.DECLINED:
            await apply_transition(session, intent, PaymentStatus.FAILED, Actor.API, "payment.failed")
        elif result.outcome is ProviderOutcome.UNKNOWN:
            await apply_transition(session, intent, PaymentStatus.UNKNOWN, Actor.API, "payment.unknown")

        response_status = 201
        response_body = serialize_payment(intent)
        key_row = await session.get(IdempotencyKey, key_row_id)
        assert key_row is not None
        await complete_idempotency_key(
            session,
            key_row,
            payment_intent_id=intent.id,
            response_status=response_status,
            response_body=response_body,
        )
        await session.commit()
        return response_status, response_body
    except Exception as exc:
        await _fail_claim_and_raise(session, key_row_id, exc)
        raise  # unreachable, _fail_claim_and_raise always re-raises; satisfies type checkers


async def get_payment(
    session: AsyncSession, *, merchant_id: uuid.UUID, payment_id: uuid.UUID
) -> PaymentIntent:
    intent = (
        await session.execute(
            select(PaymentIntent).where(
                PaymentIntent.id == payment_id, PaymentIntent.merchant_id == merchant_id
            )
        )
    ).scalar_one_or_none()
    if intent is None:
        raise PayGuardError("PAYMENT_NOT_FOUND", f"No payment found with id {payment_id}.")
    return intent


async def capture_payment(
    session: AsyncSession,
    *,
    merchant_id: uuid.UUID,
    payment_id: uuid.UUID,
    idempotency_key: str,
    raw_body: bytes,
    provider: PaymentProvider,
) -> tuple[int, dict]:
    fingerprint = compute_fingerprint("POST", f"/v1/payments/{payment_id}/capture", raw_body)
    claim = await claim_idempotency_key(
        session, merchant_id=merchant_id, idempotency_key=idempotency_key, request_fingerprint=fingerprint
    )

    if claim.outcome is ClaimOutcome.CONFLICT:
        await session.commit()
        raise PayGuardError(
            "IDEMPOTENCY_KEY_REUSED", "This idempotency key was previously used with a different request."
        )
    if claim.outcome is ClaimOutcome.IN_PROGRESS:
        await session.commit()
        raise PayGuardError(
            "REQUEST_IN_PROGRESS", "A request with this idempotency key is already being processed."
        )
    if claim.outcome is ClaimOutcome.REPLAY:
        await session.commit()
        return claim.key_row.response_status, claim.key_row.response_body

    key_row_id = claim.key_row.id
    try:
        intent = await lock_payment(session, payment_id, merchant_id)
        if intent is None:
            raise PayGuardError("PAYMENT_NOT_FOUND", f"No payment found with id {payment_id}.")

        if intent.status == PaymentStatus.SUCCEEDED.value:
            # Already captured -- safe no-op replay of a legitimate retry,
            # not an error (docs/payments.md).
            response_status, response_body = 200, serialize_payment(intent)
        elif intent.status != PaymentStatus.PROCESSING.value:
            raise PayGuardError(
                "INVALID_STATE_TRANSITION",
                f"Cannot capture a payment in status {intent.status}.",
            )
        else:
            provider_txn = await _latest_successful_provider_transaction(session, intent.id)
            if provider_txn is None:
                raise PayGuardError(
                    "INVALID_STATE_TRANSITION",
                    "This payment has no successful authorization to capture.",
                )

            result = await provider.capture(provider_txn.provider_transaction_id, intent.amount_minor)

            if result.outcome is ProviderOutcome.SUCCEEDED:
                await apply_transition(
                    session, intent, PaymentStatus.SUCCEEDED, Actor.API, "payment.succeeded"
                )
                # The payment just newly settled -- record it once, here,
                # not inside apply_transition() itself: that function is
                # also used for REFUND_PENDING -> SUCCEEDED (a partial
                # refund leaving the payment "still successful"), which is
                # NOT a new settlement and must not double-record it
                # (docs/ledger.md).
                await record_payment_settled(
                    session, payment_intent_id=intent.id, amount_minor=intent.amount_minor
                )
            elif result.outcome is ProviderOutcome.UNKNOWN:
                await apply_transition(session, intent, PaymentStatus.UNKNOWN, Actor.API, "payment.unknown")
            else:
                await apply_transition(session, intent, PaymentStatus.FAILED, Actor.API, "payment.failed")

            response_status, response_body = 200, serialize_payment(intent)

        key_row = await session.get(IdempotencyKey, key_row_id)
        assert key_row is not None
        await complete_idempotency_key(
            session,
            key_row,
            payment_intent_id=intent.id,
            response_status=response_status,
            response_body=response_body,
        )
        await session.commit()
        return response_status, response_body
    except Exception as exc:
        await _fail_claim_and_raise(session, key_row_id, exc)
        raise  # unreachable


# A payment can be refunded from SUCCEEDED (normal case) or REFUND_FAILED
# (retrying, or attempting a different amount, after a prior refund attempt
# failed at the provider) -- but never from a terminal REFUNDED payment,
# which the balance check below would catch anyway (remaining == 0), but
# rejecting on status first gives a clearer error for that case.
#
# REFUND_PENDING is *also* an acceptable starting status: it means another
# refund against this same payment is concurrently in flight. Multiple
# partial refunds racing each other is an explicitly supported, tested
# scenario (docs/refunds.md) -- rejecting a second refund just because a
# sibling hasn't finished yet would be wrong, and the balance invariant is
# already enforced independently by the reserved-sum check below, not by
# this status gate. The gate exists only to keep refunds off payments that
# were never settled successfully or are already fully refunded.
_REFUNDABLE_SOURCE_STATUSES = {
    PaymentStatus.SUCCEEDED.value,
    PaymentStatus.REFUND_FAILED.value,
    PaymentStatus.REFUND_PENDING.value,
}


async def refund_payment(
    session: AsyncSession,
    *,
    merchant_id: uuid.UUID,
    payment_id: uuid.UUID,
    idempotency_key: str,
    raw_body: bytes,
    amount_minor: int,
    provider: PaymentProvider,
) -> tuple[int, dict]:
    fingerprint = compute_fingerprint("POST", f"/v1/payments/{payment_id}/refunds", raw_body)
    claim = await claim_idempotency_key(
        session, merchant_id=merchant_id, idempotency_key=idempotency_key, request_fingerprint=fingerprint
    )

    if claim.outcome is ClaimOutcome.CONFLICT:
        await session.commit()
        raise PayGuardError(
            "IDEMPOTENCY_KEY_REUSED", "This idempotency key was previously used with a different request."
        )
    if claim.outcome is ClaimOutcome.IN_PROGRESS:
        await session.commit()
        raise PayGuardError(
            "REQUEST_IN_PROGRESS", "A request with this idempotency key is already being processed."
        )
    if claim.outcome is ClaimOutcome.REPLAY:
        await session.commit()
        return claim.key_row.response_status, claim.key_row.response_body

    key_row_id = claim.key_row.id
    try:
        # Locking the PAYMENT row (not just the new refund row) is what
        # makes the double-refund invariant airtight: every concurrent
        # refund attempt against this payment serializes on this lock, so
        # the balance check just below can never race against another
        # refund's reservation being written concurrently (docs/refunds.md,
        # ADR-002 -- this is a per-row CHECK constraint's limitation:
        # Postgres can't express "sum of sibling rows <= X" declaratively).
        intent = await lock_payment(session, payment_id, merchant_id)
        if intent is None:
            raise PayGuardError("PAYMENT_NOT_FOUND", f"No payment found with id {payment_id}.")

        if intent.status not in _REFUNDABLE_SOURCE_STATUSES:
            raise PayGuardError(
                "INVALID_STATE_TRANSITION", f"Cannot refund a payment in status {intent.status}."
            )

        reserved = (
            await session.execute(
                select(func.coalesce(func.sum(Refund.amount_minor), 0)).where(
                    Refund.payment_intent_id == intent.id,
                    Refund.status.in_(("PENDING", "SUCCEEDED")),
                )
            )
        ).scalar_one()
        remaining = intent.amount_minor - reserved
        if amount_minor > remaining:
            raise PayGuardError(
                "REFUND_EXCEEDS_PAYMENT",
                f"Refund amount {amount_minor} exceeds the remaining refundable balance {remaining}.",
            )

        provider_txn = await _latest_successful_provider_transaction(session, intent.id)
        if provider_txn is None:
            raise PayGuardError(
                "INVALID_STATE_TRANSITION", "This payment has no successful authorization to refund."
            )

        refund = Refund(payment_intent_id=intent.id, amount_minor=amount_minor, status="PENDING")
        session.add(refund)
        await session.flush()
        if intent.status != PaymentStatus.REFUND_PENDING.value:
            # First refund of this "batch" to arrive -- do the payment-level
            # transition and log it. A concurrent sibling that finds the
            # payment already REFUND_PENDING skips this (see
            # _REFUNDABLE_SOURCE_STATUSES) rather than attempting a
            # REFUND_PENDING -> REFUND_PENDING self-transition, which isn't
            # (and shouldn't be) a valid entry in the state machine.
            await apply_transition(session, intent, PaymentStatus.REFUND_PENDING, Actor.API, "refund.pending")
        # Commits (and releases the payment lock) only once the refund row
        # genuinely exists -- the next concurrent request to acquire this
        # lock will see it reflected in its own `reserved` computation.
        await session.commit()

        result = await provider.refund(provider_txn.provider_transaction_id, amount_minor, idempotency_key)

        intent = await lock_payment(session, payment_id, merchant_id)
        assert intent is not None
        refund = await session.get(Refund, refund.id)
        assert refund is not None

        refund.status = "SUCCEEDED" if result.outcome is ProviderOutcome.SUCCEEDED else "FAILED"
        if refund.status == "SUCCEEDED":
            # This specific refund settled -- record it once, here. This is
            # independent of the payment-level aggregate settlement below
            # (which only fires for whichever refund happens to be "last
            # pending"): every successfully refunded amount gets its own
            # ledger entry regardless of how many sibling refunds are still
            # in flight.
            await record_refund_settled(
                session, payment_intent_id=intent.id, amount_minor=refund.amount_minor
            )
        await session.flush()

        # Settle the payment-level status only once no sibling refund is
        # still in flight. Multiple concurrent partial refunds each hold
        # this lock in turn (never simultaneously), so whichever one
        # observes zero remaining PENDING refunds is unambiguously "the
        # last to finish" -- it alone performs the single, well-defined
        # REFUND_PENDING -> {REFUNDED, SUCCEEDED, REFUND_FAILED} transition
        # based on the complete picture. A sibling that still has other
        # PENDING refunds outstanding leaves the payment at REFUND_PENDING;
        # whichever refund turns out to be the last one will settle it.
        still_pending = (
            await session.execute(
                select(func.count())
                .select_from(Refund)
                .where(Refund.payment_intent_id == intent.id, Refund.status == "PENDING")
            )
        ).scalar_one()
        if still_pending == 0 and intent.status == PaymentStatus.REFUND_PENDING.value:
            total_refunded = (
                await session.execute(
                    select(func.coalesce(func.sum(Refund.amount_minor), 0)).where(
                        Refund.payment_intent_id == intent.id, Refund.status == "SUCCEEDED"
                    )
                )
            ).scalar_one()
            if total_refunded >= intent.amount_minor:
                await apply_transition(session, intent, PaymentStatus.REFUNDED, Actor.API, "payment.refunded")
            elif total_refunded > 0:
                await apply_transition(
                    session, intent, PaymentStatus.SUCCEEDED, Actor.API, "payment.partially_refunded"
                )
            else:
                await apply_transition(
                    session, intent, PaymentStatus.REFUND_FAILED, Actor.API, "refund.failed"
                )

        response_status = 201
        response_body = serialize_refund(refund)
        key_row = await session.get(IdempotencyKey, key_row_id)
        assert key_row is not None
        await complete_idempotency_key(
            session,
            key_row,
            payment_intent_id=intent.id,
            refund_id=refund.id,
            response_status=response_status,
            response_body=response_body,
        )
        await session.commit()
        return response_status, response_body
    except Exception as exc:
        await _fail_claim_and_raise(session, key_row_id, exc)
        raise  # unreachable


async def get_refund(session: AsyncSession, *, merchant_id: uuid.UUID, refund_id: uuid.UUID) -> Refund:
    stmt = (
        select(Refund)
        .join(PaymentIntent, Refund.payment_intent_id == PaymentIntent.id)
        .where(Refund.id == refund_id, PaymentIntent.merchant_id == merchant_id)
    )
    refund = (await session.execute(stmt)).scalar_one_or_none()
    if refund is None:
        raise PayGuardError("REFUND_NOT_FOUND", f"No refund found with id {refund_id}.")
    return refund
