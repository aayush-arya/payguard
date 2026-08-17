# Transactional Outbox Worker (Phase 6)

Status: implemented. Covers the consumer side of ADR-003 -- the producer side
(writing `outbox_events` rows transactionally alongside a payment mutation) already
existed since Phase 3.

## What it does

`apps/worker/main.py` is a standalone polling loop, independent of the API process
(see "Why a separate process" below). Each iteration it calls
`outbox.run_batch()`, which claims and dispatches due `outbox_events` rows one at a
time via `packages/outbox/worker.py`.

```
PENDING (available_at <= now) --dispatch succeeds--> PROCESSED
PENDING --dispatch fails, attempt_count < MAX_ATTEMPTS--> PENDING (available_at pushed forward)
PENDING --dispatch fails, attempt_count >= MAX_ATTEMPTS--> DEAD_LETTER
DEAD_LETTER --operator calls requeue_dead_letter()--> PENDING (attempt_count reset to 0)
```

`MAX_ATTEMPTS = 8`, exponential backoff with full jitter
(`uniform(0, min(300s, 1s * 2^(attempt-1)))`) -- full jitter rather than a fixed
delay so many events failing at once (e.g. a downstream outage) don't all retry in
lockstep and hammer whatever's on the other end the moment it recovers.

## A deliberate departure from "never hold a lock across a network call"

`docs/architecture.md` section 8 is emphatic that a database transaction must never
span an external network call -- that rule is why `payments.service.create_payment()`
releases its row lock before calling `provider.authorize()`. The outbox worker does
the opposite: `process_next()` holds one event's `SELECT ... FOR UPDATE SKIP LOCKED`
lock for the entire duration of `dispatcher.dispatch()`.

This is intentional, not an oversight. The rule in section 8 exists because payment
provider calls are slow, unpredictable, third-party HTTP requests where a stalled
provider could stall the database. In this phase, `LoggingDispatcher` is a fast,
local, in-process operation -- there's no equivalent risk. Holding the lock buys real
simplicity in exchange: a worker crash mid-dispatch just rolls the transaction back,
leaving the event `PENDING` and visible to the next poll (via `SKIP LOCKED` no longer
seeing a lock on it) -- no separate "PROCESSING with staleness-based reclaim" state
machine is needed, unlike `idempotency_keys`, which genuinely needs that machinery
because it really does span a network call (ADR-001 section 4.4).

**This tradeoff should be revisited if a real message broker is ever substituted for
`LoggingDispatcher`.** A broker publish call has real network latency and failure
modes; holding a Postgres row lock across it reintroduces exactly the risk section 8
warns about. At that point, the fix is to adopt the same pattern
`idempotency_keys` already uses: release the lock before dispatch, track an
in-flight state with a staleness timeout, and reclaim orphaned in-flight events the
same way a crashed idempotency claim gets reclaimed.

## Why a separate process

The worker is a distinct deployable from the API (`apps/worker` vs. `apps/api`),
matching `docker-compose.yml`'s `api`/`worker` split described in Phase 1. It must
keep retrying a dead-lettered-but-recoverable event regardless of whether the API
instance that originally wrote it is still running, and it needs to scale
independently -- outbox backlog is a function of write volume and downstream
dispatch latency, not API request concurrency.

## Concurrency: multiple worker replicas

`SELECT ... FOR UPDATE SKIP LOCKED` is what lets multiple worker replicas poll the
same table without contending on the same row: a row already locked by one
worker's transaction is invisible to another worker's claim query, rather than
making it wait. `tests/concurrency/test_outbox_worker_race.py` proves this
directly -- 8 concurrent worker loops draining 40 events land on exactly 40 dispatches
total, no event dispatched twice, no event left unprocessed.

## Operator escape hatch

`requeue_dead_letter(session, event_id)` moves a `DEAD_LETTER` row back to `PENDING`
with a reset attempt count, for after the underlying issue (e.g. a downstream outage)
is fixed. This never happens automatically -- an event that exhausted its retries
needs a human (or a future admin endpoint) to decide it's safe to replay, not a timer.

## Testing

| Layer | What it proves | Where |
|---|---|---|
| Unit | Backoff never exceeds the cap, grows with attempt count on average, saturates correctly, `MAX_ATTEMPTS` is a small finite bound | `tests/unit/test_outbox_backoff.py` |
| Integration | Retry-then-succeed, dead-lettering after `MAX_ATTEMPTS`, `available_at` is respected, requeue works (and is a no-op for non-dead-lettered events), and -- most importantly -- outbox rows written by the real Phase 3 payment API get picked up and dispatched with zero producer-side changes | `tests/integration/test_outbox_worker.py` |
| Concurrency | 8 concurrent worker replicas against 40 events: every event dispatched exactly once, none skipped, none duplicated | `tests/concurrency/test_outbox_worker_race.py` |

Run everything: `pytest tests/` (requires `docker compose up -d postgres redis` and
`alembic upgrade head` first). Run the worker itself:
`python apps/worker/main.py`. 108 tests total, all passing as of this phase.
