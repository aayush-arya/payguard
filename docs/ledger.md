# Double-Entry Ledger (Phase 9)

Status: implemented. Records every payment and refund settlement as a balanced,
immutable debit/credit pair, per [ADR-007](adr/ADR-007-ledger-design.md).

## Accounts

| Account | Meaning |
|---|---|
| `Merchant Receivable` | What the merchant is owed |
| `Payment Clearing` | Settled funds held pending payout |
| `Refund Liability` | Money owed back out to a customer |

A payment settling writes:

```
Debit  Merchant Receivable   $X
Credit Payment Clearing      $X
```

A refund settling writes:

```
Debit  Refund Liability      $X
Credit Merchant Receivable   $X
```

Matches the product brief's own example exactly, and
`tests/integration/test_ledger.py::test_partial_refunds_write_ledger_entries_matching_the_100_30_20_50_example`
runs that exact $100 → $30/$20/$50 sequence against the real database.

## Why ledger writes are tied to specific events, not to generic transitions

The obvious-looking design is "whenever `payment_intents.status` becomes `SUCCEEDED`,
write a settlement entry." That's wrong here: per `docs/refunds.md`, a payment
*returns* to `SUCCEEDED` after each partial refund that doesn't fully exhaust it
(`REFUND_PENDING -> SUCCEEDED`). Hooking ledger writes into `apply_transition()`
generically would record a second, bogus "payment settled" entry every time a partial
refund leaves the payment at `SUCCEEDED` again -- double-counting revenue that was
never actually received twice.

Instead, `record_payment_settled()` and `record_refund_settled()` are called from the
exact call sites where a **genuine** settlement happens:

- `capture_payment()` — only in the branch where `PROCESSING -> SUCCEEDED` actually
  fires (never in the idempotent "already `SUCCEEDED`" no-op replay branch).
- `webhooks.service._handle_payment_outcome()` — only when the `PROCESSING ->
  SUCCEEDED` transition actually fires via webhook confirmation (the "already
  applied" no-op branch returns before reaching it).
- `refund_payment()` — whenever a *specific* refund's own status flips to
  `SUCCEEDED`, independent of whatever the aggregate payment-level status ends up at.
  This is why concurrent partial refunds each get their own ledger entry regardless
  of which one turns out to be "last pending" for the payment-level settlement logic
  (`docs/refunds.md`).

## The balance invariant

`packages/ledger/service.py` separates pure entry-pair *construction*
(`build_payment_settled_pair`, `build_refund_settled_pair`) from the `session.add()`
side effect specifically so the invariant -- every pair this module can produce has
equal debit and credit amounts, sharing one `ledger_transaction_id` -- is directly
property-tested with Hypothesis over arbitrary amounts
(`tests/property/test_ledger_invariants.py`), no database required.

`packages/ledger/invariants.py` provides the operational checks:
`ledger_transaction_is_balanced()` (per-transaction), `global_ledger_balance()`
(`sum(debits)` vs `sum(credits)` across the whole table), and
`find_unbalanced_ledger_transactions()` -- a `GROUP BY ledger_transaction_id HAVING
sum(debit) != sum(credit)` query that should always return empty. This is the
reconciliation-style audit query an operator (or a future scheduled job, Phase 10)
runs to catch a writer bug, not something load-bearing for correctness by itself --
the writer already can't construct an unbalanced pair.

## Immutability: a real database-level backstop, not just a promise

ADR-007 said ledger rows are "never updated or deleted" and flagged a `REVOKE
UPDATE, DELETE` grant as something to consider in Phase 9. A straight `REVOKE` turned
out to be impractical given this project's single-DB-role setup (the same `payguard`
role runs both migrations and the application; revoking its own privileges would
block Alembic from managing the table in future migrations). Instead, Phase 9 adds a
`BEFORE UPDATE` / `BEFORE DELETE` trigger
(`packages/database/migrations/versions/ab10ded442e0_*.py`) that raises on any
attempt to mutate a `ledger_entries` row, regardless of which role or code path
attempts it:

```sql
CREATE TRIGGER ledger_entries_no_update BEFORE UPDATE ON ledger_entries ...
CREATE TRIGGER ledger_entries_no_delete BEFORE DELETE ON ledger_entries ...
```

This makes "the ledger is append-only" a provable fact about the data, not just
about the application code that's supposed to write it --
`tests/integration/test_ledger.py::test_ledger_entries_cannot_be_updated` and
`test_ledger_entries_cannot_be_deleted` attempt direct mutation and assert it's
rejected. `TRUNCATE` (used by the test suite's per-test cleanup) is unaffected --
Postgres treats `TRUNCATE` as a separate trigger event from row-level `DELETE`, so
test isolation between runs still works.

## Testing

| Layer | What it proves | Where |
|---|---|---|
| Property | Every entry pair the ledger writer can construct has equal debit/credit amounts, a shared `ledger_transaction_id`, and distinct accounts -- for any amount, any payment id, without a database | `tests/property/test_ledger_invariants.py` |
| Integration | Entries written correctly (right accounts, right amounts, balanced) on capture, on webhook-confirmed settlement, and on refund; a failed refund writes nothing; an idempotent capture replay doesn't double-write; the $100/$30/$20/$50 example stays globally balanced; the immutability trigger blocks both `UPDATE` and `DELETE` | `tests/integration/test_ledger.py` |
| Concurrency | The existing 10-concurrent-refunds test (`docs/refunds.md`) now also asserts the global ledger balance invariant holds after real concurrent settlement writes, not just the refund-amount invariant | `tests/concurrency/test_refund_race.py` |

Run everything: `pytest tests/` (requires `docker compose up -d postgres redis` and
`alembic upgrade head` first). 152 tests total, all passing as of this phase.
