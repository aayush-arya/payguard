# Database (Phase 2)

Status: implemented. This describes what Phase 2 actually built, not the Phase 1
design intent -- see [`architecture.md`](architecture.md) section 7 for the original
ERD this was built against.

## Running it locally

```bash
docker compose up -d postgres redis
cp .env.example .env
pip install -e ".[dev]"
alembic upgrade head
```

Postgres listens on `localhost:5434` (not 5432/5433 -- both were already in use by
other local services on the dev machine this was built on; see `docker-compose.yml`).

## Schema

All 13 tables from the Phase 1 ERD are implemented in
[`packages/database/models.py`](../packages/database/models.py) via SQLAlchemy 2.0
declarative models, with one Alembic migration
(`packages/database/migrations/versions/`) generated from them. `merchants`,
`customers`, `payment_methods`, `payment_intents`, `payment_attempts`,
`provider_transactions`, `idempotency_keys`, `payment_events`, `refunds`,
`outbox_events`, `webhook_events`, `ledger_entries`, `audit_logs`.

Status columns (`payment_intents.status`, `payment_attempts.status`, `refunds.status`,
etc.) are `VARCHAR` with a `CHECK` constraint enumerating valid values, not native
Postgres `ENUM` types -- adding a new status is a plain migration instead of `ALTER
TYPE ... ADD VALUE`, which cannot run inside a transaction in older Postgres versions
and complicates rollback. `domain.state_machine` (see below) is the actual authority
on which values and transitions are valid; the CHECK constraints are a database-level
backstop against a bug that bypasses the state machine, not the primary mechanism.

Two things worth calling out that a reviewer would ask about:

- **`idempotency_keys.refund_id`** exists now, nullable, unused until Phase 8. It lets
  refunds reuse the exact same claim protocol as payments (one shared table, one shared
  code path) instead of a parallel implementation once refund idempotency is built.
- **The refund-sum invariant (§15 of the product brief) is deliberately not a CHECK
  constraint.** Postgres `CHECK` constraints can only see the row being written, not
  sibling rows, so "sum(refunds) <= payment amount" cannot be expressed that way. It is
  enforced transactionally instead: `SELECT ... FOR UPDATE` the payment row, compute
  remaining balance, insert the new refund in the same transaction (ADR-002). Phase 8
  implements that write path; the `refunds` table exists now so the rest of the schema
  (e.g. `idempotency_keys.refund_id`) can reference it.

## Idempotency claim protocol

[`packages/idempotency/service.py`](../packages/idempotency/service.py) implements the
protocol from [ADR-001](adr/ADR-001-idempotency-strategy.md):
`claim_idempotency_key()` races concurrent callers against the
`uq_idempotency_keys_merchant_key` unique constraint via
`INSERT ... ON CONFLICT DO NOTHING`, and returns one of four outcomes: `CLAIMED`
(proceed), `REPLAY` (a prior call already completed -- return its stored response
verbatim), `CONFLICT` (same key, different request fingerprint -- reject), or
`IN_PROGRESS` (another call is actively working on this key right now).

A `PENDING` claim whose owner crashed before completing is detected via the
`locked_at` timestamp: past a configurable staleness window (default 30s), the next
caller atomically reclaims it via an `UPDATE ... WHERE status = ... AND locked_at = ...
RETURNING`, which is safe under concurrent reclaim attempts because Postgres
re-evaluates the `WHERE` clause after acquiring the row's lock (`READ COMMITTED`) --
a second, slower reclaimer's `UPDATE` matches zero rows instead of double-reclaiming.

## State machine

[`packages/domain/state_machine.py`](../packages/domain/state_machine.py) is a pure,
DB-free module: two closed transition tables (`PaymentStatus`, `RefundStatus`) plus an
`Actor` enum so a transition can be restricted to a specific caller -- concretely, only
`Actor.RECONCILIATION` may resolve a payment out of `UNKNOWN`, matching
[ADR-008](adr/ADR-008-reconciliation-strategy.md). Every payment status is reachable
from `CREATED` and every terminal status (`FAILED`, `REFUNDED`) has zero outgoing
transitions -- both are asserted directly by property tests
(`tests/property/test_state_machine_invariants.py`), not just spot-checked by example.

## Testing

| Layer | What it proves | Where |
|---|---|---|
| Unit | Every transition in the Phase 1 table is allowed; everything else (including `FAILED -> SUCCEEDED` and `UNKNOWN -> SUCCEEDED` from a non-reconciliation actor) is rejected | `tests/unit/test_state_machine.py` |
| Property | The transition table can never regress into something unsafe (terminal states never gain outgoing edges, `UNKNOWN` never resolves outside reconciliation) regardless of future edits | `tests/property/test_state_machine_invariants.py` |
| Integration | Every `CHECK`/`UNIQUE` constraint in the schema is actually enforced by Postgres when written to directly, bypassing application logic; the idempotency claim/replay/conflict/reclaim protocol behaves correctly against a real database | `tests/integration/` |
| Concurrency | 100 real, concurrent Postgres connections racing the same idempotency key -- identical payloads, mixed payloads, and a stale-claim reclaim race -- produce exactly one `payment_intents` row every time, verified by querying the database afterward, not by trusting HTTP-shaped return values | `tests/concurrency/test_idempotency_race.py` |

Run everything: `pytest tests/` (requires `docker compose up -d postgres` and
`alembic upgrade head` first). 65 tests, all passing as of this phase.
