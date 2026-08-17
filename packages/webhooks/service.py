"""Webhook receipt and effect application (ADR-006).

Two-phase, matching docs/architecture.md section 11:

1. `receive_webhook()` -- fast path, runs inside the HTTP request. Dedups on
   (provider_name, provider_event_id) via the same INSERT ... ON CONFLICT DO
   NOTHING pattern idempotency_keys uses (ADR-001), then writes an outbox
   event in the same transaction and acks. Nothing about *what the webhook
   means* is interpreted here.
2. `apply_webhook_event()` -- the effect-application path, run by the outbox
   worker (packages/outbox) as a dispatcher, never inline in the request.
   This is what actually moves a payment's state.

`apply_webhook_event()` deliberately does not call session.commit(): it runs
inside the outbox worker's process_next(), which commits once at the end,
atomically alongside marking the outbox event PROCESSED (see docs/outbox.md
for why the worker holds its lock through dispatch).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from database.models import OutboxEvent, PaymentAttempt, PaymentIntent, ProviderTransaction, WebhookEvent
from domain.state_machine import Actor, PaymentStatus, is_valid_payment_transition
from ledger.service import record_payment_settled
from payments.service import apply_transition, lock_payment
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession


async def receive_webhook(
    session: AsyncSession,
    *,
    provider_name: str,
    provider_event_id: str,
    event_type: str,
    raw_payload: dict,
    signature: str,
) -> None:
    insert_stmt = (
        pg_insert(WebhookEvent)
        .values(
            provider_name=provider_name,
            provider_event_id=provider_event_id,
            event_type=event_type,
            raw_payload=raw_payload,
            signature=signature,
            processing_status="RECEIVED",
        )
        .on_conflict_do_nothing(constraint="uq_webhook_events_provider_event")
        .returning(WebhookEvent)
    )
    inserted = (await session.execute(insert_stmt)).scalar_one_or_none()
    if inserted is not None:
        # Same transaction as the dedup insert -- if this commits, an outbox
        # event for it is guaranteed to exist too (ADR-003).
        session.add(
            OutboxEvent(
                aggregate_type="webhook_event",
                aggregate_id=inserted.id,
                event_type="webhook.received",
                payload={"webhook_event_id": str(inserted.id)},
            )
        )
    # Ack either way -- acknowledging *receipt*, not re-triggering
    # *processing*. A provider resending the same event must never see this
    # as a delivery failure and retry even harder.
    await session.commit()


async def _handle_payment_outcome(
    session: AsyncSession, webhook_event: WebhookEvent, target_status: PaymentStatus
) -> None:
    data = webhook_event.raw_payload.get("data", {})
    provider_transaction_id = data.get("provider_transaction_id")
    if not provider_transaction_id:
        webhook_event.processing_status = "IGNORED"
        return

    stmt = (
        select(PaymentIntent)
        .join(PaymentAttempt, PaymentAttempt.payment_intent_id == PaymentIntent.id)
        .join(ProviderTransaction, ProviderTransaction.payment_attempt_id == PaymentAttempt.id)
        .where(ProviderTransaction.provider_transaction_id == provider_transaction_id)
        .limit(1)
    )
    intent = (await session.execute(stmt)).scalar_one_or_none()
    if intent is None:
        webhook_event.processing_status = "IGNORED"
        return

    locked = await lock_payment(session, intent.id, intent.merchant_id)
    assert locked is not None

    if locked.status == target_status.value:
        # Already applied -- via a prior webhook delivery, or the
        # synchronous API path (capture) winning the race. Safe no-op, not
        # an error: this is exactly the "duplicate webhook -> one logical
        # state transition" guarantee ADR-006 promises.
        webhook_event.processing_status = "PROCESSED"
        return

    if not is_valid_payment_transition(PaymentStatus(locked.status), target_status, Actor.WEBHOOK):
        # A genuinely contradictory late arrival (e.g. a "failed" webhook
        # after this payment already settled SUCCEEDED through another
        # path) -- flagged for investigation, not silently applied
        # (docs/architecture.md section 11).
        webhook_event.processing_status = "IGNORED"
        return

    event_type_suffix = target_status.value.lower()
    await apply_transition(session, locked, target_status, Actor.WEBHOOK, f"webhook.{event_type_suffix}")
    if target_status is PaymentStatus.SUCCEEDED:
        # The payment just newly settled via webhook confirmation rather
        # than an explicit capture call -- record it exactly like
        # capture_payment() does for the synchronous path. This can't
        # double-fire: the "already applied" no-op branch above returns
        # before reaching here if the payment was already SUCCEEDED.
        await record_payment_settled(session, payment_intent_id=locked.id, amount_minor=locked.amount_minor)
    webhook_event.processing_status = "PROCESSED"


async def _handle_payment_succeeded(session: AsyncSession, webhook_event: WebhookEvent) -> None:
    await _handle_payment_outcome(session, webhook_event, PaymentStatus.SUCCEEDED)


async def _handle_payment_failed(session: AsyncSession, webhook_event: WebhookEvent) -> None:
    await _handle_payment_outcome(session, webhook_event, PaymentStatus.FAILED)


# refund.succeeded / refund.failed are recognized wire event types (the
# provider may send them) but still have no handler: refunds (Phase 8) are
# only settled synchronously via POST /v1/payments/{id}/refunds today, not
# confirmed asynchronously the way payment.succeeded is. They fall through
# to the IGNORED branch below, acknowledged and recorded, not dropped
# silently and not retried forever.
_EVENT_HANDLERS: dict[str, Callable[[AsyncSession, WebhookEvent], Awaitable[None]]] = {
    "payment.succeeded": _handle_payment_succeeded,
    "payment.failed": _handle_payment_failed,
}


async def apply_webhook_event(session: AsyncSession, webhook_event_id: uuid.UUID) -> None:
    webhook_event = await session.get(WebhookEvent, webhook_event_id)
    if webhook_event is None or webhook_event.processing_status != "RECEIVED":
        return

    handler = _EVENT_HANDLERS.get(webhook_event.event_type)
    if handler is None:
        webhook_event.processing_status = "IGNORED"
        return

    await handler(session, webhook_event)
