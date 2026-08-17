# ADR-003: Transactional Outbox

## Status
Accepted

## Problem
After a payment write commits, the system needs to reliably trigger side effects
(metrics emission, downstream notification, eventually a message-bus publish) without
the classic dual-write failure: the database transaction commits, but the separate
"publish this event" step crashes, times out, or is simply never reached, and the
event is lost forever with no trace that it should have existed. Conversely, retrying
a naive publish-then-commit ordering can emit an event for a payment that then fails to
commit, notifying the world about something that never actually happened.

## Options considered

1. **Publish directly from application code after commit, no outbox.** Simplest, but
   reintroduces the dual-write problem: a crash or exception between `commit()` and
   `publish()` silently drops the event, and there is no record that it was ever owed.
   Rejected.
2. **Two-phase commit across the database and a message broker.** Technically closes
   the gap, but 2PC across heterogeneous systems is operationally heavy, not supported
   cleanly by common brokers, and adds a coordination failure mode of its own. Rejected
   as disproportionate to this project's scale.
3. **Transactional outbox: write the event as a row in the same database transaction
   as the business mutation; a separate poller reads and dispatches it.** Chosen.
4. **Outbox backed by Kafka/RabbitMQ as the dispatch target instead of a plain
   Postgres-polled table.** A real broker would matter at higher fan-out/throughput,
   but at this project's scale, `SELECT ... FOR UPDATE SKIP LOCKED` against a Postgres
   table already gives safe concurrent consumption by multiple worker replicas without
   adding an operational component whose own failure modes would need to be handled.
   Documented as a deliberate scale tradeoff, revisitable if this ever needs true
   fan-out to multiple heterogeneous consumers.

## Decision
`outbox_events` rows are inserted in the exact same transaction as the payment (or
refund) row they describe. If that transaction commits, the event's existence is
guaranteed — there is no window where the payment exists in the database but the fact
that something happened to it doesn't. A separate worker process polls for
`status = PENDING AND available_at <= now()` using `SELECT ... FOR UPDATE SKIP LOCKED`,
which allows multiple worker replicas to claim different rows concurrently without
contending on the same lock or double-processing a row.

Event lifecycle: `PENDING → PROCESSING → PROCESSED`, or on a dispatch failure
`PENDING → PROCESSING → PENDING` with `attempt_count` incremented and
`available_at` pushed forward by an exponential-backoff-with-jitter delay, until
`attempt_count` exceeds a configured maximum, at which point the row moves to
`DEAD_LETTER` — excluded from normal polling, but retained and queryable for operator
inspection or manual replay, never deleted.

## Why this prevents "DB committed but event publish failed"
The event *is* a database row, written atomically alongside the fact it describes.
"Publish" is redefined from "a side effect that must happen exactly once at commit
time" into "a fact that must eventually be dispatched, at least once" — and at-least-once
dispatch with idempotent consumers (already required elsewhere in this system, see
[ADR-001](ADR-001-idempotency-strategy.md)) is a solvable, testable problem. The
outbox never needs to know whether the *original* transaction will succeed, because it
is only written if that transaction succeeds — it participates in the same atomic
commit rather than reacting to it afterward.

## Tradeoffs
- Adds polling latency between "payment committed" and "event dispatched," bounded by
  the worker's poll interval — this is an explicit availability/latency tradeoff in
  exchange for delivery guarantees, appropriate here because outbox events are not on
  the synchronous request/response path.
- Postgres itself becomes the queue, which means outbox backlog is now a metric to
  watch (`outbox_backlog`, §23 of the architecture doc) and a potential source of table
  bloat if dead-lettered/processed rows aren't periodically archived — an operational
  concern documented here rather than solved prematurely with partitioning that isn't
  needed at this project's scale.

## Failure modes
- **Worker crashes mid-dispatch after claiming a row (`PROCESSING`) but before marking
  it `PROCESSED`**: the row's `FOR UPDATE` lock is released when the worker's
  connection drops, and the row is picked up again by the next poll — dispatch must
  therefore be idempotent on the consumer side, same requirement as webhook delivery.
- **Two worker replicas poll simultaneously**: `SKIP LOCKED` guarantees they claim
  disjoint row sets; neither blocks on the other.
- **A downstream dispatch target is down for an extended period**: exponential backoff
  spaces out retries instead of hammering it, and the dead-letter threshold prevents an
  event from being retried forever, surfacing it for operator attention instead.
