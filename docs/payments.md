# Payments API (Phase 3)

Status: implemented. Covers `POST /v1/payments`, `GET /v1/payments/{id}`,
`POST /v1/payments/{id}/capture`, plus `GET /v1/health` / `GET /v1/ready`, and the
MockProvider (Phase 4 pulled forward, since Phase 3's `authorize()` call is
meaningless without a provider to call). This document records the judgment calls
made while implementing against the Phase 1 design, and where this phase's behavior
is a deliberate simplification pending a later phase.

## Why authorize() leaves the payment in PROCESSING, not a new status

The Phase 1 state machine (`docs/architecture.md` section 6, already shipped as a
Postgres `CHECK` constraint in Phase 2) has no status for "authorized, awaiting
capture" -- only `CREATED → PROCESSING → SUCCEEDED/FAILED/...`. Adding one now would
mean revising an already-shipped, already-tested schema for a Phase 3 convenience.

Instead: a successful `authorize()` call records a `payment_attempts` row with
`status = SUCCEEDED` (the *authorization* succeeded, a hold was placed) but leaves
`payment_intents.status` at `PROCESSING`. `POST /v1/payments/{id}/capture` is the
call that actually finalizes the payment, moving `PROCESSING → SUCCEEDED` -- a
transition that was already valid in the Phase 1 table. This gives the exact
"create → authorize → capture → success" flow the product brief's Demo 1 asks for,
with zero schema changes, by treating `PROCESSING` as "not yet finalized" rather than
"work in progress on the authorize call specifically."

The cost of this choice: `PROCESSING` is now overloaded -- it means both "the
authorize call hasn't returned yet" and "authorize succeeded, awaiting capture."
Phase 3 disambiguates by inspecting `payment_attempts`/`provider_transactions`
directly (see `capture_payment()` in `packages/payments/service.py`) rather than by
adding a new top-level status. If this ever becomes a real ergonomics problem --
e.g. once the dashboard needs to show "awaiting capture" as a distinct filter --
the fix is a dedicated `AUTHORIZED` status added as its own migration, not a
workaround bolted onto `PROCESSING`.

## Why capture requires an Idempotency-Key too

The product brief's endpoint sketch only shows an explicit `Idempotency-Key` example
on refunds, not capture. But capture has the exact same double-execution hazard as
payment creation: without a claim mechanism, two concurrent capture requests could
both pass a `SELECT ... FOR UPDATE` check ("status is PROCESSING, proceed") in two
separate short transactions before either has actually called `provider.capture()` --
the architecture's own rule against holding a DB lock across a network call
(`docs/architecture.md` section 8) means the lock *must* be released between the
check and the provider call, which reopens exactly the TOCTOU race idempotency keys
exist to close.

Rather than invent a second mechanism (an advisory lock held across the provider
call, which the architecture doc already argues against holding locks unnecessarily
across network calls), capture reuses the exact same `idempotency_keys` claim/replay
protocol as payment creation (ADR-001) -- the same table, the same unique constraint,
the same code path. This is why `idempotency_keys.refund_id` and the general
claim/replay/conflict machinery were designed to be resource-agnostic back in Phase 2.

## Why capturing an already-SUCCEEDED payment is a 200, not an error

Real clients retry. A capture request against a payment that's already been captured
(by an earlier, successful call under a *different* idempotency key -- e.g. the
client's own retry logic generated a new key because it didn't record the first
key) is a legitimate, safe-to-ignore situation, not a client bug. `capture_payment()`
checks current status under the row lock and returns the current (already-`SUCCEEDED`)
payment with `200 OK` instead of `422 INVALID_STATE_TRANSITION` in that one case --
every other non-`PROCESSING` status (`CREATED`, `FAILED`, `UNKNOWN`, `REFUND_*`) is
still rejected, since capturing from those states is never valid.

## Why this phase is fully synchronous

The request lifecycle diagram in `docs/architecture.md` section 3 shows the API
responding to the client before the authorize call resolves, implying an async
handoff to a worker. That handoff depends on the outbox *consumer* existing
(Phase 6) -- the outbox *events* are already written transactionally in this phase
(every state transition inserts one, per ADR-003), but nothing processes them yet.
Rather than fake an async response that doesn't actually mean anything yet,
`create_payment()` and `capture_payment()` both block until the provider call and
resulting transition are fully committed. When Phase 6 lands the worker, the outbox
rows this phase already writes are exactly what it will consume -- no retrofit
needed on the producer side.

## TEMPORARY_FAILURE and UNKNOWN are deliberately not auto-resolved

Per ADR-005, a `TEMPORARY_FAILURE` from the provider should be retried with backoff
by a retry engine, and per ADR-008 an `UNKNOWN` outcome should be resolved by
reconciliation -- neither exists yet (Phase 6/11 and Phase 10, respectively). Rather
than approximate them inline in the request handler (which would violate ADR-005's
core rule against ad hoc retries), a `TEMPORARY_FAILURE` attempt is recorded and the
payment is left in `PROCESSING`; an `UNKNOWN` outcome moves the payment to `UNKNOWN`.
Both are real, honest terminal-for-now states that a later phase will resolve -- not
silently converted to `FAILED` to make the demo look cleaner.

## Authentication

Merchants authenticate with `Authorization: Bearer <api_key>`. There is no merchant
signup endpoint -- provisioning is out-of-band via `scripts/seed_merchant.py`, which
prints the raw key once (only its SHA-256 hash is ever stored; see
`domain.security` for why a fast hash is the *correct* choice for a high-entropy
random token, unlike a user password). Every payment lookup filters by
`merchant_id` at the query level (`get_payment`, `capture_payment`), verified by
`test_merchant_cannot_read_another_merchants_payment` in
`tests/integration/test_payment_api.py`.

## Testing

| Layer | What it proves | Where |
|---|---|---|
| Integration | Auth (missing/invalid key), idempotency (replay, conflict, required-header), validation errors, declined/unknown outcomes, tenant isolation, capture state transitions and its idempotent no-op case | `tests/integration/test_payment_api.py` |
| Concurrency | 100 real concurrent HTTP requests through the ASGI app with the same Idempotency-Key -- identical and mixed payloads -- produce exactly one `payment_intents` row and exactly one `payment_attempts` row (one provider authorization), verified against the database | `tests/concurrency/test_payment_api_race.py` |

A note on test infrastructure: `database.session.get_engine()`/`get_sessionmaker()`
are process-wide `lru_cache` singletons, correct for a real long-lived app with one
event loop. pytest-asyncio gives each test function its own event loop, and asyncpg
connections can't cross event loops -- the `api_client` fixture in `tests/conftest.py`
resets that cache (disposing the old engine) around every test that uses it, so the
app under test always gets an engine bound to the test's own loop.

Run everything: `pytest tests/` (requires `docker compose up -d postgres redis` and
`alembic upgrade head` first). 85 tests, all passing as of this phase.
