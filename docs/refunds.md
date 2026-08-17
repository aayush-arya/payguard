# Refunds (Phase 8)

Status: implemented. Covers `POST /v1/payments/{id}/refunds` and `GET /v1/refunds/{id}`:
full refunds, multiple partial refunds, the double-refund balance invariant, refund
idempotency, and retry-after-failure.

## The balance invariant, and why it isn't a CHECK constraint

`refunds.amount_minor > 0` is a `CHECK` constraint (Phase 2). "Sum of a payment's
refunds never exceeds the payment amount" is **not**, because Postgres `CHECK`
constraints can only see the row being written, not its siblings -- there is no
declarative way to express "sum of sibling rows <= X" (`docs/database.md`,
[ADR-002](adr/ADR-002-postgresql-locking-strategy.md)).

The invariant is enforced transactionally instead, in `refund_payment()`
(`packages/payments/service.py`):

1. `SELECT ... FOR UPDATE` the **payment** row (not just a new refund row). Every
   concurrent refund attempt against the same payment serializes on this lock.
2. While holding it, compute `reserved = sum(amount_minor) WHERE status IN
   ('PENDING', 'SUCCEEDED')` and reject with `409 REFUND_EXCEEDS_PAYMENT` if the new
   amount would push the total past the payment amount.
3. Insert the new `refunds` row (status `PENDING`) -- this is the "reservation" --
   and commit, releasing the lock.
4. Call `provider.refund()` **outside** the lock (never hold a DB lock across a
   network call, `docs/architecture.md` section 8).
5. Re-acquire the lock, finalize the refund row to `SUCCEEDED` or `FAILED`.

Because the reservation (step 3) commits before the lock is released, and the balance
check (step 2) always re-reads the current reserved sum under a fresh lock, two
concurrent refund attempts can never both observe stale headroom and both proceed --
the second one to acquire the lock always sees the first one's reservation already
counted.

## A concurrency bug this design caught before it shipped

The first version of this code transitioned `payment_intents.status` to
`REFUND_PENDING` in step 3 and back to `SUCCEEDED`/`REFUNDED` in step 5, treating
`REFUND_PENDING` as a normal linear state (matching the Phase 1 diagram literally).
The concurrency test (`tests/concurrency/test_refund_race.py`) caught two real bugs
this caused under **multiple concurrent partial refunds against the same payment**,
which the Phase 1 diagram never had to account for (it was drawn for one refund at a
time):

1. **Sibling refunds got spuriously rejected.** While refund A held `REFUND_PENDING`
   between steps 3 and 5 (calling the provider), refund B would acquire the lock,
   see `payment_intents.status == REFUND_PENDING`, and reject with
   `422 INVALID_STATE_TRANSITION` -- even though B's amount would have fit fine
   under the balance check. `REFUND_PENDING` was accidentally being used as a mutex
   over the *entire payment*, not just as a status label.
2. **Finalization order corrupted later transitions.** Whichever refund finalized
   first flipped the payment straight back to `SUCCEEDED`. When a second concurrent
   refund then tried to finalize, it attempted `SUCCEEDED -> SUCCEEDED` (or
   `SUCCEEDED -> REFUNDED`) -- neither is a valid entry in the transition table,
   which only allows those targets *from* `REFUND_PENDING`.

**The fix**, now in place:

- `REFUND_PENDING` is added to `_REFUNDABLE_SOURCE_STATUSES`: a refund attempt is
  allowed to proceed whether the payment is `SUCCEEDED`, `REFUND_FAILED`, or already
  `REFUND_PENDING` (a sibling in flight). The balance invariant is what actually
  protects correctness here, not this status gate -- the gate only exists to keep
  refunds off payments that were never settled or are already fully refunded
  (`REFUNDED`, terminal).
- The payment transitions `-> REFUND_PENDING` only once per "batch": the first
  refund to arrive when the payment isn't already there does it and logs it; siblings
  that find it already `REFUND_PENDING` skip the transition entirely (avoiding a
  `REFUND_PENDING -> REFUND_PENDING` self-transition, which correctly isn't and
  shouldn't be in the state machine).
- Settlement (`REFUND_PENDING -> REFUNDED` / `SUCCEEDED` / `REFUND_FAILED`) happens
  only once, performed by whichever finalizing refund observes **zero remaining
  `PENDING` refunds** for that payment under its own lock hold. Since every
  finalization is serialized by the same row lock, exactly one refund will ever see
  "zero remaining pending" at the right moment -- that one settles the aggregate
  status from the complete picture (total successfully refunded vs. payment amount);
  every other concurrent refund leaves the payment at `REFUND_PENDING` for the
  eventual last one to resolve.

This is the kind of bug that a sequential test (create payment, refund once, assert)
cannot catch -- `tests/integration/test_refunds.py`'s sequential partial-refund test
passed against the *first*, buggy version too. Only firing genuinely concurrent
requests and checking the database afterward caught it.

## Retry after failure

A refund that fails at the provider (`refund.status = FAILED`, payment moves to
`REFUND_FAILED` if no other refund on that payment has ever succeeded) is retryable:
`REFUND_FAILED` is one of the allowed starting statuses. A subsequent refund attempt
-- same amount or different, same idempotency key or a new one -- proceeds normally.
`MockProvider.refund()` supports the same deterministic-scenario pattern as
`authorize()`, but since `refund()` has no token to carry a marker, the scenario is
read from the **idempotency key** instead (e.g. `f"refund-declined-{uuid4()}"`
deterministically declines).

## Idempotency

Refunds reuse the exact `idempotency_keys` claim/replay protocol payments and
captures use (ADR-001) -- the same table, same unique constraint, same code path.
This is why `idempotency_keys.refund_id` existed as a nullable column since Phase 2,
unused until now: `complete_idempotency_key()` was extended to accept it, so a
completed refund claim points at the refund it created exactly the way a completed
payment claim points at the payment.

## What "get the latest successful authorization" means for refunds

Refunds (like captures) refund against the payment's most recent successful
`provider_transactions` row, found via `_latest_successful_provider_transaction()` --
shared code, extracted from `capture_payment()` during this phase since both
operations need "the provider transaction id backing this payment's authorization,"
not two near-identical queries.

## Testing

| Layer | What it proves | Where |
|---|---|---|
| Unit | The new `REFUND_PENDING -> SUCCEEDED` state machine transition (partial refund succeeded, payment remains fundamentally successful) is allowed; existing transitions are unaffected | `tests/unit/test_state_machine.py` |
| Integration | Full refunds, partial refunds summing exactly to the payment amount, over-refund rejection (both "already fully refunded" and "this amount doesn't fit"), refunding an unsettled payment, refund idempotency (replay + conflict), declined refunds, retry-after-failure, `GET /v1/refunds/{id}`, tenant isolation | `tests/integration/test_refunds.py` |
| Concurrency | 10 concurrent refund requests for an amount where only some can fit (`floor(payment/refund_amount)`) -- exactly that many succeed, the rest are rejected with `REFUND_EXCEEDS_PAYMENT`, and the total refunded **never** exceeds the payment amount, verified against the database. A second test: 10 concurrent retries under the *same* idempotency key collapse to exactly one refund row | `tests/concurrency/test_refund_race.py` |

Run everything: `pytest tests/` (requires `docker compose up -d postgres redis` and
`alembic upgrade head` first). 141 tests total, all passing as of this phase.
