# ADR-002: PostgreSQL Locking Strategy

## Status
Accepted

## Problem
Multiple actors — the synchronous API request, the outbox worker retrying a stuck
attempt, an inbound webhook, and the reconciliation job — can all attempt to read and
mutate the same `payment_intents` row at effectively the same time. Without a locking
strategy, two of these could both observe the same "current" state, both decide a
transition is valid, and both write, with the loser's write silently clobbering
information the winner's write depended on (a classic lost-update race).

## Options considered

1. **No locking, last-write-wins.** Rejected immediately — this is the exact bug this
   project is built to prevent.
2. **Optimistic concurrency (version column, `UPDATE ... WHERE id=$1 AND version=$2`,
   caller retries on zero rows affected).** Correct, and lock-free, but pushes a retry
   loop onto every caller for what is, in this system, an *expected and frequent*
   occurrence (worker vs. webhook racing on the same payment). Every one of those call
   sites would need its own backoff/retry logic, which is more surface area for bugs
   than a single well-tested locking primitive.
3. **Pessimistic row locking via `SELECT ... FOR UPDATE`, short critical section, one
   consistent lock-acquisition order.** Chosen. Losers block briefly and then observe
   the winner's committed state directly — no retry loop required at each call site.
4. **`SERIALIZABLE` isolation for all payment writes.** Rejected as the default: it
   would catch the same races but forces the application to handle serialization
   failures everywhere, and it's a broader (and more expensive) guarantee than needed
   given every correctness-critical write is already scoped to a single locked row.
   `SERIALIZABLE` is reserved for read-only, multi-row consistency snapshots (ledger
   balance reporting), documented in [ADR-007](ADR-007-ledger-design.md).

## Decision
`SELECT ... FOR UPDATE` on the specific `payment_intents` row (or `refunds` row, for
refund transitions) is acquired immediately before validating and applying any state
transition, inside a transaction kept as short as possible — no network calls while the
lock is held (see `architecture.md` §8). The outbox worker uses
`SELECT ... FOR UPDATE SKIP LOCKED` when claiming a batch of pending events, which is a
different lock use: it lets multiple worker replicas pull *different* rows concurrently
without blocking each other, rather than serializing access to one shared row.

Lock ordering discipline: within a single transaction, if both a payment row and a
refund row must be locked, the payment row is always locked first. This is documented
here so any future code that needs to lock more than one row type has a single rule to
follow instead of inventing its own order.

## What each lock prevents, who owns it, and how deadlocks are avoided

| Lock | Prevents | Owning transaction | Deadlock avoidance |
|---|---|---|---|
| `payment_intents` row, `FOR UPDATE` | Two actors (worker retry, webhook, API) applying conflicting transitions to the same payment concurrently | The short transaction performing exactly one transition | Always the first lock acquired in any transaction touching both a payment and its refunds; critical section excludes network calls, so lock hold time is bounded by DB latency alone |
| `refunds` row, `FOR UPDATE` (with parent `payment_intents` locked first if both are touched) | Concurrent partial refunds summing past the original payment amount | The transaction applying a refund's state transition or computing remaining refundable balance | Acquired only after the payment lock in the same transaction; never acquired standalone across multiple refund rows in a fixed order that could invert with another transaction |
| `outbox_events` batch, `FOR UPDATE SKIP LOCKED` | Two worker replicas processing the same outbox row twice | The worker's poll-and-claim transaction | `SKIP LOCKED` means a busy row is simply skipped, not waited on — structurally cannot deadlock against another worker |
| `idempotency_keys` unique constraint (not a lock, but the analogous mechanism) | Duplicate payment creation under the same key | The transaction attempting the `INSERT ... ON CONFLICT` | N/A — constraint violation is resolved instantly by Postgres, no held lock to deadlock on |

## Transaction failure handling
If a transaction holding a `FOR UPDATE` lock fails (deadlock detected, connection
drop, serialization failure), Postgres aborts it and releases the lock automatically;
the application treats this as a transient error and retries the *transition attempt*
from scratch — re-reading current state under a fresh lock — rather than retrying a
stale in-memory decision. Because critical sections are short and lock ordering is
fixed, deadlocks are expected to be rare in practice; the concurrency test suite
(`tests/concurrency/`) is where this is verified empirically rather than assumed.

## Tradeoffs
- Pessimistic locking means a burst of concurrent requests against one payment will
  see the losers stall for the duration of the winner's transaction rather than fail
  fast. Given transactions are kept sub-millisecond-to-low-millisecond (no network
  calls inside them), this is judged acceptable relative to pushing retry logic to
  every caller.
