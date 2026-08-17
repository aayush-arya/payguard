# ADR-006: Webhook Processing

## Status
Accepted

## Problem
Providers deliver payment outcome events (`payment.succeeded`, `payment.failed`,
`refund.succeeded`, `refund.failed`) asynchronously via webhook, and real-world
providers routinely deliver the same event multiple times (their own retry logic on
delivery failure), out of order, and concurrently with the synchronous API path that
may already be applying the same transition. The webhook endpoint is also a public,
unauthenticated-by-default HTTP endpoint, making it a natural target for spoofed
requests unless explicitly secured.

## Options considered

1. **Process each webhook synchronously and immediately inline in the request
   handler, with no dedup tracking.** Simplest, but a provider retrying delivery (which
   they will, on any non-2xx or slow response) would reprocess the same event
   repeatedly, and a slow handler risks the provider timing out and retrying even more
   aggressively. Rejected.
2. **Track only "have we seen this raw payload before" via a hash.** Fails when a
   provider resends a semantically identical event with a different envelope
   (timestamp, delivery id) — hashing the payload wouldn't dedup it. Rejected.
3. **Dedup on `(provider_name, provider_event_id)` via a unique constraint, acknowledge
   fast, apply the actual state transition asynchronously under the same row-locking
   discipline as the synchronous path.** Chosen.

## Decision
Every inbound webhook is first verified (signature over the raw body + timestamp
tolerance window, see §13/threat-model), then an attempt is made to
`INSERT INTO webhook_events (provider_name, provider_event_id, ...) ON CONFLICT
(provider_name, provider_event_id) DO NOTHING`. If the insert succeeds, this is the
first time this exact event has been seen, the endpoint acknowledges `200 OK`
immediately, and the actual business effect (applying a state transition) is applied
asynchronously by the worker, which acquires the same `SELECT ... FOR UPDATE` lock on
the target payment that the synchronous API path uses (ADR-002) — so whichever actor,
webhook or API, gets there first wins the race cleanly, and the loser's attempted
transition is simply validated against the now-current state and accepted, rejected, or
turned into a no-op by the state machine, never blindly overwritten.

If the insert conflicts (event already seen), the endpoint still returns `200 OK` —
acknowledging *receipt*, not re-triggering *processing* — so the provider does not
interpret an idempotent no-op as a delivery failure and retry again.

## Why deduplication happens before parsing/processing
Acknowledging fast and deduplicating on a stable provider-assigned event id, rather
than deriving identity from decoded payload contents, means processing order and retry
timing on the provider's side cannot cause the same logical event to be applied twice
— the ledger of "have we seen this" is a database constraint, exactly analogous to the
idempotency-key design in [ADR-001](ADR-001-idempotency-strategy.md), applied to
inbound events instead of inbound requests.

## Ordering
Webhooks are not guaranteed to arrive in the order they were generated. Rather than
trying to reconstruct provider-side ordering, every transition application goes through
the same state-machine validation as every other path in the system — an out-of-order
`payment.failed` arriving after `payment.succeeded` was already applied is rejected as
an invalid transition (not silently applied), and logged for investigation, since a
provider sending contradictory terminal states is itself an anomaly worth surfacing
rather than a normal thing to reconcile away silently.

## Tradeoffs
- Asynchronous processing means there is a small window between "webhook acknowledged"
  and "transition actually applied" — acceptable because nothing external is blocking
  on it, and it keeps the webhook endpoint's response time independent of database lock
  contention.
- Dedup on `provider_event_id` trusts the provider to assign stable, unique ids per
  logical event; `MockProvider` is built to do this deliberately so this assumption is
  actually exercised by tests, including the duplicate-and-out-of-order chaos scenarios
  (§25 of the architecture brief).

## Failure modes
- **Provider sends the same event 20 times**: 1 row inserted, 19 conflicts, 20 `200 OK`
  acks, at most one transition application. This is the demo scenario "Duplicate
  Webhook" and is asserted directly against the database, not just HTTP status codes.
- **Webhook and synchronous API race to apply the same transition**: resolved by the
  shared row lock; whichever commits first wins, the second is validated against
  updated state and becomes a no-op or a legitimately rejected transition.
- **Signature verification fails**: request rejected with `401
  WEBHOOK_SIGNATURE_INVALID` before touching `webhook_events` at all — an
  unauthenticated caller never gets to influence dedup state.
