# Webhook Processing (Phase 7)

Status: implemented. Covers `POST /v1/webhooks/provider`: signature verification,
replay protection, deduplication, and asynchronous effect application via the Phase 6
outbox worker.

## Two-phase design, now that a worker actually exists

ADR-006 always described webhook processing as two phases -- a fast synchronous ack,
and asynchronous effect application by "the worker" -- but Phase 6 (the outbox
worker) didn't exist yet when Phase 3 shipped. Now it does, so Phase 7 wires webhooks
into it directly instead of approximating async behavior:

1. **`receive_webhook()`** (`packages/webhooks/service.py`) runs inside the HTTP
   request. It dedups on `(provider_name, provider_event_id)` via
   `INSERT ... ON CONFLICT DO NOTHING` against the `webhook_events` unique constraint
   -- the exact same pattern `idempotency_keys` uses for inbound *requests* (ADR-001),
   applied here to inbound *events* (ADR-006). If this insert wins, an outbox event
   (`webhook.received`) is written in the same transaction. The HTTP response is
   `200 OK` either way -- a duplicate delivery is acknowledged, not reprocessed, so
   the provider never sees what looks like a delivery failure and retries harder.
2. **`apply_webhook_event()`** is invoked by the outbox worker
   (`outbox.dispatchers.WebhookEffectDispatcher`, see below) once the `webhook.received`
   event comes up for dispatch. This is where the actual payment state transition
   happens -- never inline in the request handler.

## Threat model

The webhook endpoint is public and carries no merchant `Authorization` header --
anyone can `POST` to it. The only thing separating a genuine provider notification
from a forged one is proof of possession of a shared secret, demonstrated via
HMAC-SHA256 signature over the **raw** request body plus a timestamp
(`packages/webhooks/security.py`).

| Threat | Mitigation |
|---|---|
| Forged webhook (attacker POSTs a fake `payment.succeeded`) | HMAC-SHA256 signature required; verification fails closed (any missing/malformed/wrong header rejects with `401 WEBHOOK_SIGNATURE_INVALID`) |
| Replay of a captured, genuinely-valid signature | Timestamp is part of the signed payload; a signature older than `DEFAULT_TOLERANCE_SECONDS` (5 minutes, symmetric -- also rejects implausibly-future timestamps) is rejected even though the HMAC itself checks out |
| Timing attack against signature comparison | `hmac.compare_digest`, not `==` |
| Verifying a re-serialized (not raw) body | Verification runs over `await request.body()` bytes *before* `json.loads()` -- see `apps/api/routers/webhooks.py`. Parsing then re-serializing to verify would let key reordering, whitespace, or number formatting differences silently break or spoof the signature |
| Provider re-delivering the same event many times | Dedup on `(provider_name, provider_event_id)`, a database unique constraint, not an application-level check |
| Two webhooks (or a webhook and a merchant API call) racing to apply the same transition | Both paths go through `payments.lock_payment()`/`apply_transition()`, which acquire the same `FOR UPDATE` row lock and validate against the state machine -- the loser observes already-applied state and no-ops (see below) |

**Known Phase 7 scope boundary**: there is one global `WEBHOOK_SECRET`, matching the
one shared `MockProvider` instance this project has. A platform onboarding real,
independent PSP accounts per merchant would key secrets by
`(merchant_id, provider_name)` instead -- not built now because nothing in this
project yet needs more than one provider identity.

## Idempotent application, not just idempotent receipt

Deduplicating on `provider_event_id` prevents the same *event* from being applied
twice. It does **not**, by itself, prevent two *different* events (a webhook and a
concurrent merchant `capture` call, or two different webhook deliveries confirming
the same underlying fact through different `provider_event_id`s) from racing to
apply the same transition. `_handle_payment_outcome()` in
`packages/webhooks/service.py` handles this explicitly:

- If the payment is **already** in the target status: no-op, mark the webhook
  `PROCESSED`. This is not an error -- it's exactly the "duplicate webhook -> one
  logical state transition" guarantee, and it's also what makes the capture/webhook
  race in the tests converge safely regardless of which side wins.
- If the transition **isn't valid** from the payment's current status (e.g. a
  `payment.failed` webhook arriving after the payment already settled `SUCCEEDED`
  through another path): the webhook is marked `IGNORED`, not silently applied and
  not treated as a dispatch failure to retry. A genuinely contradictory late arrival
  is a signal worth a human looking at, not something to paper over.

## Wiring into the outbox worker

`outbox.dispatchers.WebhookEffectDispatcher` is the dispatcher `apps/worker/main.py`
now runs (replacing the Phase 6 `LoggingDispatcher`, which it still uses internally
for observability on every event). For `webhook.received` events specifically, it
calls `apply_webhook_event()` using the **same session** `process_next()` is holding
the outbox row's lock under -- not a session of its own. This is what makes the
webhook's database effects commit atomically with the outbox event being marked
`PROCESSED`: see `docs/outbox.md` for why the worker holds its lock through dispatch
in the first place, and why that's specifically safe for a fast, local operation like
this one.

This required widening `OutboxDispatcher.dispatch()`'s signature to accept the
session (it previously only took the event) -- a real protocol change, not a
workaround, since Phase 6's `LoggingDispatcher` had no reason to need one yet.

## What a `payment.succeeded` webhook means here

Per `docs/payments.md`, a synchronously-authorized payment stays `PROCESSING` until
an explicit `capture` call finalizes it. A `payment.succeeded` webhook is the
*alternate* path to that same `PROCESSING -> SUCCEEDED` transition -- modeling a
provider that settles asynchronously and confirms via webhook instead of (or in
addition to) an explicit capture response. The webhook is matched to a payment via
`data.provider_transaction_id`, looked up through
`provider_transactions -> payment_attempts -> payment_intents`, since a real provider
only ever knows its own transaction id, never PayGuard's internal UUIDs.

`refund.succeeded`/`refund.failed` are recognized wire event types with no handler
yet -- refunds don't exist until Phase 8. They're acknowledged and recorded
(`processing_status = IGNORED`), not dropped or retried forever.

## Testing

| Layer | What it proves | Where |
|---|---|---|
| Unit | Valid signatures pass; missing/malformed headers, wrong secret, tampered body, and stale/future timestamps outside the tolerance window are all rejected | `tests/unit/test_webhook_signature.py` |
| Integration | Valid/invalid signature at the HTTP boundary, dedup on duplicate delivery, unknown-provider-transaction and unrecognized-event-type handled gracefully, and the full receive -> outbox -> worker -> applied-transition pipeline end to end against the real Phase 3 payment API | `tests/integration/test_webhooks.py` |
| Concurrency | **Demo 4**: 20 concurrent identical webhook deliveries dedup to exactly 1 `webhook_events` row and exactly 1 logical `PROCESSING -> SUCCEEDED` transition (not 20). A concurrent merchant `capture` call racing the webhook's effect application converges to exactly one transition regardless of which side wins | `tests/concurrency/test_webhook_race.py` |

Run everything: `pytest tests/` (requires `docker compose up -d postgres redis`,
`alembic upgrade head`, and `WEBHOOK_SECRET` set in `.env` first). 126 tests total,
all passing as of this phase.
