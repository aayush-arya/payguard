# Reconciliation (Phase 10)

Status: implemented. Resolves payments in `UNKNOWN` status by asking the provider
directly, per [ADR-008](adr/ADR-008-reconciliation-strategy.md) — the answer to "what
happens when the provider succeeds but our server times out" (product brief Demo 3),
proven end to end in `tests/integration/test_reconciliation.py`.

## Scope: UNKNOWN only, not "stale PROCESSING"

ADR-008 originally sketched reconciling both `UNKNOWN` payments and payments "stuck
in `PROCESSING` past an expected SLA window." By the time Phase 10 was built, Phase 3
had already settled `PROCESSING` into meaning "authorized, awaiting an explicit
`capture` call" (`docs/payments.md`) — a legitimately long-lived, expected state, not
a stuck one. A payment can correctly sit in `PROCESSING` for hours waiting for a
merchant to call `capture`; treating that as needing reconciliation would be
reconciling against a false premise inherited from a design that changed underneath
it. `find_payments_needing_reconciliation()` is scoped to `status == UNKNOWN` only.

## How an `UNKNOWN` payment gets resolved without a provider transaction id

The hard part: when `authorize()` returns `UNKNOWN`, it also returns
`provider_transaction_id = None` — the whole point is that we never received enough
of a response to learn an ID. `get_payment_status(provider_transaction_id)` (the
"normal" lookup) is therefore useless here; there's nothing to look up *by*.

The fix, added to the provider abstraction this phase:
`get_payment_status_by_idempotency_key(idempotency_key)`. This mirrors a real PSP
capability (e.g. Stripe's idempotency-key lookup) — the one piece of information we
*do* still have is the idempotency key the original request carried, and a
well-built provider tracks requests by that key internally regardless of whether its
response reached us. `MockProvider` now tracks two outcomes per idempotency key: the
*caller-visible* one (`UNKNOWN`, for the `timeout`/`unknown_result` scenarios) and
the *true* one the provider "actually recorded" (`SUCCEEDED` for `timeout`,
`DECLINED` for `unknown_result`) — only reachable via the new lookup method, never by
retrying `authorize()` (which correctly keeps returning `UNKNOWN`, consistent with
ADR-005's "never blindly retry" rule).

Reconciliation finds *which* idempotency key to ask about via
`_original_idempotency_key()`: the earliest `idempotency_keys` row for that payment
by creation time. A payment can accumulate several such rows over its life (creation,
capture, each refund); the earliest one is always the `create_payment` claim — the
call whose `authorize()` response could actually have been lost.

## Resolution outcomes

| `ReconciliationReport.result` | Meaning | Payment status after |
|---|---|---|
| `MATCHED` | Payment wasn't `UNKNOWN` when we checked (already resolved by another path) | Untouched |
| `RESOLVED_SUCCEEDED` | Provider confirms it actually succeeded | `SUCCEEDED` (see below) |
| `RESOLVED_FAILED` | Provider confirms it actually failed | `FAILED` |
| `STILL_UNKNOWN` | The provider itself doesn't know yet either | `UNKNOWN` (unchanged) |
| `MISSING_INTERNAL_TRANSACTION` | No idempotency key on record to even ask about | `UNKNOWN` (unchanged) |
| `AMOUNT_MISMATCH` / `CURRENCY_MISMATCH` | Provider's answer doesn't match our records | `UNKNOWN` (unchanged) |

Every one of these writes exactly one immutable `reconciliation_reports` row — a new
table this phase added (not in the original Phase 2 ERD, matching every other
append-only audit table: `payment_events`, `webhook_events`). Nothing is silently
"fixed": a mismatch is flagged for human review, never auto-corrected, per ADR-008.

## Why `RESOLVED_SUCCEEDED` settles the payment directly, not to `PROCESSING`

The Phase 1 state machine only allows `UNKNOWN -> SUCCEEDED` (via `RECONCILIATION`),
never `UNKNOWN -> PROCESSING`. This means reconciliation confirming "the
authorization actually succeeded" has no way to represent "authorized, now awaiting
an explicit capture" the way a normal `authorize()` success does — there's no
intermediate leg to land on. Rather than add one (another schema change this late),
`RESOLVED_SUCCEEDED` is treated as full settlement: a `payment_attempts` row and
(if the provider supplied one) a `provider_transactions` row are backfilled, and
`record_payment_settled()` writes the ledger entry exactly like a completed capture
would. This is a deliberate simplification, not an oversight — reconstructing a lost
authorization after the fact and then requiring a *second* explicit capture call
would be a strange UX for something reconciliation already had to invent from
scratch.

## Concurrency: re-checking under a fresh lock

`reconcile_payment()` releases the payment's row lock before calling the provider
(never hold a DB lock across a network call, `docs/architecture.md` section 8), then
re-acquires it to apply the result — and re-checks the status under that fresh lock
rather than trusting what it read before. If something else resolved the payment
while the provider call was in flight (another reconciliation pass, a webhook
confirming the same payment through a completely different path), the second check
finds `status != UNKNOWN` and reports `MATCHED` instead of attempting a transition
that's no longer valid. This is the same "re-check after re-acquiring the lock"
pattern already used by `webhooks.service._handle_payment_outcome()`.

## Triggering a reconciliation pass

There's no scheduler yet (Phase 12) and no dashboard button yet (Phase 13) — the
on-demand path ADR-008 describes is `scripts/run_reconciliation.py`, which calls
`run_reconciliation_pass()` directly. Its documented limitation: it constructs a
*fresh* `MockProvider()`, which has no memory of authorizations made by a separately
running API process (the mock's state is in-memory, per-instance, not persisted) —
useful as a demo/test harness, not as an operational tool against a live server. A
real provider adapter, backed by an actual external service, wouldn't have this
limitation.

## Testing

| Scenario | What it proves | Where |
|---|---|---|
| Demo 3 (`pm_demo_timeout`) | End-to-end: create → authorize succeeds internally but response is lost → `UNKNOWN` → reconcile → `SUCCEEDED`, with a backfilled `payment_attempts`/`provider_transactions` row and a ledger entry | `tests/integration/test_reconciliation.py::test_reconciliation_resolves_timeout_to_succeeded_demo_3` |
| `pm_demo_unknown_result` | Resolves to `FAILED`, no ledger entry written | `test_reconciliation_resolves_unknown_result_to_failed` |
| `pm_demo_still_unknown` | Provider itself can't answer — stays `UNKNOWN`, reported honestly | `test_reconciliation_reports_still_unknown_when_provider_cannot_answer` |
| Already-settled payment | `MATCHED`, no-op | `test_reconciliation_of_already_settled_payment_is_a_matched_noop` |
| No idempotency key on record | `MISSING_INTERNAL_TRANSACTION`, left `UNKNOWN` | `test_reconciliation_reports_missing_internal_transaction_without_an_idempotency_key` |
| Amount/currency mismatch (via a stub provider) | Flagged, never auto-corrected | `test_reconciliation_flags_amount_mismatch_without_auto_correcting`, `..._currency_mismatch...` |
| Batch pass | `run_reconciliation_pass()` finds and resolves every `UNKNOWN` payment in one call | `test_run_reconciliation_pass_resolves_every_unknown_payment` |

Run everything: `pytest tests/` (requires `docker compose up -d postgres redis` and
`alembic upgrade head` first). Run a pass on demand: `python scripts/run_reconciliation.py`.

## A flaky test fixed along the way

While running the full suite for this phase, `test_failed_dispatch_is_retried_and_eventually_succeeds`
(Phase 6) surfaced as flaky: it asserted `outbox_events.available_at > datetime.now()`
immediately after scheduling a retry, but the outbox worker's full-jitter backoff can
legitimately compute a delay close to zero (`compute_backoff(1)` is
`uniform(0, 1.0)` seconds) — if the DB round-trip between scheduling and asserting
took longer than the jitter, the assertion failed even though nothing was wrong. Fixed
by comparing against a timestamp captured *before* the call instead of `now()` after
it, which is what the test actually needed to prove (a real backoff was scheduled),
without depending on wall-clock timing that a fast test run could race past.
