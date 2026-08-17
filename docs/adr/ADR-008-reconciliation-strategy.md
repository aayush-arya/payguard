# ADR-008: Reconciliation Strategy

## Status
Accepted

## Problem
When a provider call times out or the connection drops after the request was
transmitted, the system genuinely does not know what happened — the provider may have
processed the payment successfully, declined it, or never received it. Neither
guessing success, guessing failure, nor blindly retrying (ADR-005) is safe. Some
process must eventually resolve `UNKNOWN` payments to a true terminal state, and must
also be able to detect a broader class of internal/provider divergence beyond just
`UNKNOWN` (e.g. amount mismatches, a provider transaction with no matching internal
record).

## Options considered

1. **Leave `UNKNOWN` payments unresolved, require manual operator lookup.** Safe, but
   doesn't scale and leaves the merchant-facing payment status wrong for an
   unbounded time. Rejected as the sole mechanism, though manual lookup remains
   available as a fallback for cases automation can't resolve.
2. **Resolve `UNKNOWN` by having the *client* retry with the same idempotency key**,
   relying on the provider's own idempotency to avoid a double charge. This depends
   entirely on the *provider* correctly implementing request idempotency, which is
   outside this system's control and not something to bet financial correctness on.
   Rejected as the primary mechanism, though it is a reasonable secondary effect of a
   correctly-idempotent retry once reconciliation confirms `FAILED`.
3. **A dedicated reconciliation job that periodically calls `get_payment_status` on
   the provider for every payment in `UNKNOWN` or stuck in `PROCESSING` past an SLA
   window, and compares full internal vs. provider state (not just `UNKNOWN` cases) to
   catch a broader class of drift.** Chosen.

## Decision
A scheduled (and on-demand-triggerable) reconciliation job selects payments in
`UNKNOWN` state or `PROCESSING` past a configured SLA, and for each, calls the
provider's `get_payment_status`. The comparison against internal state produces one of:
`MATCHED`, `MISMATCH` (state disagrees), `MISSING_PROVIDER_TRANSACTION` (we have a
record, provider doesn't), `MISSING_INTERNAL_TRANSACTION` (provider has a record, we
don't — e.g. from a request that never got an internal row committed, an important
signal in its own right), `AMOUNT_MISMATCH`, `CURRENCY_MISMATCH`, or `STILL_UNKNOWN` if
the provider itself can't yet answer. Every pass writes an immutable reconciliation
report row — the report is itself part of the audit trail, not a transient log line.

When reconciliation resolves an `UNKNOWN` payment to a definite `SUCCEEDED` or `FAILED`,
it applies that transition through the same state-machine validation and row-locking
discipline as every other path in the system ([ADR-002](ADR-002-postgresql-locking-strategy.md))
— reconciliation is a privileged *caller* of the state machine, not an exception to it.
This is also the **only** legitimate path by which a payment can move `FAILED →
SUCCEEDED`-shaped corrections in the broader sense of "we thought it failed but the
provider says otherwise": strictly, that transition only ever occurs from `UNKNOWN`,
never directly overwriting an already-settled `FAILED`, which keeps the state machine's
transition table (architecture.md §6) the single source of truth for what's allowed.

## Tradeoffs
- Introduces a detection delay bounded by the reconciliation schedule — a payment can
  sit in `UNKNOWN` for up to one scheduling interval before resolution is attempted.
  This is an explicit, documented tradeoff: bounded delay to get a *correct* answer
  beats an immediate but potentially wrong guess.
- Reconciliation depends on the provider adapter's `get_payment_status` being accurate,
  which is why that method is a mandatory part of the provider interface
  ([ADR-004](ADR-004-provider-abstraction.md)) rather than optional.

## Failure modes
- **Provider also can't answer during reconciliation** (e.g. its own internal
  processing is delayed): recorded as `STILL_UNKNOWN`, retried on the next scheduled
  pass, never escalated to a guessed resolution.
- **Reconciliation job crashes mid-run**: each payment is resolved independently in its
  own transaction; a crash loses at most the in-flight item, which is picked up again
  by the next scheduled run — reconciliation is naturally idempotent since it always
  starts from "what is currently `UNKNOWN`/stale," not from a saved cursor that could
  desync.
- **A mismatch is detected that isn't a simple `UNKNOWN` resolution** (e.g.
  `AMOUNT_MISMATCH`): not auto-corrected. Flagged in the report and surfaced on the
  dashboard's Reconciliation page for human review, since silently "fixing" a financial
  discrepancy without investigation is its own risk.
