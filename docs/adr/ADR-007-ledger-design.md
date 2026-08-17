# ADR-007: Ledger Design

## Status
Accepted

## Problem
`payment_intents.status` and `refunds.status` tell you the current state of an
operation, but they don't, by themselves, give a financially auditable record of money
movement over time, and they don't provide a checkable invariant that nothing was ever
lost, duplicated, or fabricated. A serious payment system needs an immutable financial
record independent of the mutable operational state machine, with an invariant that can
be checked at any point in history: total debits equal total credits.

## Options considered

1. **No separate ledger; treat `payment_intents`/`refunds` rows as the financial
   record.** Simplest, but these rows are mutable operational state (a payment's
   `status` changes in place), which makes them unsuitable as an audit trail — there is
   no way to prove after the fact that a balance was always correct at every point in
   time, only what the balance is *now*.
2. **Single-entry ledger (one row per financial event, signed amount).** Better than
   nothing, but doesn't self-check — a bug that creates a stray entry or drops one
   produces no detectable inconsistency, because there's no dual representation of the
   same movement to compare against.
3. **Double-entry ledger: every financial event writes two immutable rows (a debit and
   a matching credit to different accounts) within one `ledger_transaction_id`, with
   `sum(debits) == sum(credits)` as a checkable invariant.** Chosen — this is the
   standard technique specifically because it makes entire classes of bugs (a missed or
   duplicated write) detectable by summing, rather than requiring you to trust that the
   code was correct.

## Decision
`ledger_entries` is append-only: rows are inserted, never updated or deleted. Every
financial event (payment success, refund) writes exactly two rows sharing a
`ledger_transaction_id` — e.g. a successful $100 payment debits `Merchant Receivable`
$100 and credits `Payment Clearing` $100; a $20 refund later debits `Refund Liability`
$20 and credits `Merchant Receivable` $20. The invariant `sum(debits) ==
sum(credits)` holds both per-`ledger_transaction_id` (checked synchronously at write
time — a ledger writer that can't balance a transaction refuses to write it) and
globally across the whole table (checked as a scheduled property test / reconciliation
report, since a global sum is a multi-row read best done as a read-only consistency
snapshot).

Ledger writes happen in the same database transaction as the state transition that
causes them (e.g. `PROCESSING → SUCCEEDED` and its two ledger rows commit together),
following the same transaction-boundary discipline as the rest of the system (no
network calls inside the transaction, one commit or nothing) — so a crash cannot
produce a state transition without its corresponding ledger entries, or vice versa.

## Why entries are never mutated
Allowing an existing ledger entry to be edited would defeat the purpose of having a
ledger at all — the entire value of the double-entry invariant is that it lets you
trust a historical record without re-verifying application logic. Corrections
(reversals, adjustments) are modeled as new, additional entries that net out the
original, never as edits to what already happened. This mirrors real accounting
practice and is enforced at the application layer (no `UPDATE`/`DELETE` code paths
against `ledger_entries` exist) with a database-level backstop considered for Phase 9
(a restrictive `REVOKE UPDATE, DELETE` grant on the table for the application's DB
role).

## Isolation level for the balance-invariant check
Per-transaction balance is enforced synchronously and doesn't need special isolation —
it's checked before a single transaction commits. The *global* invariant check (used in
reconciliation reporting) reads across potentially many rows and benefits from
`SERIALIZABLE` isolation specifically for that read, so a concurrently-committing
ledger write can't produce a torn, mid-write read that looks unbalanced when nothing is
actually wrong — this is the one place in the system `SERIALIZABLE` is used, as noted in
[ADR-002](ADR-002-postgresql-locking-strategy.md).

## Tradeoffs
- Doubles the number of rows written per financial event compared to single-entry,
  and requires every future financial feature (e.g. a chargeback account) to be
  modeled correctly as a debit/credit pair rather than an ad hoc signed amount —
  a deliberate constraint that keeps the invariant meaningful as the system grows.

## Failure modes
- **Process crashes between applying a state transition and writing ledger entries**:
  impossible by construction, since both happen in the same transaction — either both
  are committed or neither is.
- **A ledger-writing bug tries to write an unbalanced transaction**: rejected at the
  writer level before insertion (debits/credits computed and checked before any row is
  written), not caught later by a periodic audit — the periodic global check exists as
  a second line of defense against bugs in that first check, not as the primary
  guarantee.
