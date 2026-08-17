# ADR-005: Retry Policy

## Status
Accepted

## Problem
Not every provider failure should be retried, and blind retries of a payment operation
are actively dangerous: if a request that already succeeded on the provider's side is
retried because the *response* was lost, a naive retry can create a second charge. The
system needs a principled way to decide when retrying is safe, when it is unsafe, and
when the honest answer is "we don't know yet."

## Options considered

1. **Retry every failure a fixed number of times with fixed delay.** Simplest, but
   conflates "the provider is temporarily overloaded, retry is safe and helpful" with
   "the card was declined, retrying changes nothing" and, worst of all, with "we don't
   know if the first attempt succeeded, retrying might double-charge." Rejected as
   financially unsafe.
2. **Never retry automatically; always require a new client-initiated request.** Safe,
   but pushes transient-failure handling entirely onto merchants, which is worse
   reliability than the system can safely provide itself for genuinely transient
   provider issues. Rejected as needlessly conservative for the transient case.
3. **Classify every provider outcome into `Permanent | Transient | Unknown`, and apply
   a different policy to each: never retry Permanent, retry Transient with bounded
   exponential backoff + jitter, and never blindly retry Unknown — route it to
   reconciliation instead.** Chosen.

## Decision
Every provider adapter result is classified before any retry decision is made:

- **Permanent** (invalid payment method, insufficient funds, malformed request): the
  operation is marked `FAILED` immediately. Retrying cannot change a permanent
  provider decision, and retrying wastes provider rate-limit budget and risks looking
  like retry abuse to the provider.
- **Transient** (provider unavailable, temporary network error, `503`): eligible for
  automatic retry, using the outbox/worker's exponential backoff with jitter (base
  delay, capped max delay, capped max attempts) already described in
  [ADR-003](ADR-003-transactional-outbox.md). After max attempts, the operation moves
  to `FAILED` (not silently abandoned) with the failure reason recorded.
- **Unknown** (timeout or connection loss *after* the request was transmitted to the
  provider): explicitly **not** retried by the retry engine. It is set to `UNKNOWN` and
  handed to reconciliation ([ADR-008](ADR-008-reconciliation-strategy.md)), because the
  system cannot tell whether the original request already succeeded — retrying here is
  exactly the scenario that could double-charge a customer.

## Why blind retries are never acceptable for payment operations
A retry is only safe when the retrying party knows the original attempt definitely did
not take effect. A connection timeout tells you nothing about the provider's internal
state — the request may have arrived and been fully processed before the response was
lost. Treating "no response" as equivalent to "no effect" is the single most common way
a naive payment integration ends up double-charging customers. This system treats "no
response" as a distinct, first-class outcome (`UNKNOWN`) with its own resolution path,
rather than collapsing it into either success or failure.

## Tradeoffs
- Transient retries still carry a small residual risk: if the *retry itself* also
  experiences a lost response, it becomes another `UNKNOWN`, not a resolved outcome.
  This is acceptable because it degrades to the same safe `UNKNOWN`-and-reconcile path
  rather than compounding into a duplicate charge.
- Classification is only as good as the provider adapter's mapping (ADR-004); a
  misclassified Permanent-as-Transient error would cause pointless retries (wasteful
  but not unsafe), while a misclassified Transient-as-Unknown would cause
  under-retrying (safe but slower) — the classification is deliberately biased toward
  the safer error when uncertain.

## Failure modes
- **Provider returns `503` repeatedly past max attempts**: operation reaches `FAILED`
  with `failure_reason` populated; not retried indefinitely, not silently dropped.
- **Timeout after request transmitted**: `UNKNOWN`, no automatic retry, reconciliation
  scheduled.
- **Retry engine itself crashes mid-backoff**: state lives in the outbox row
  (`attempt_count`, `available_at`), so a restarted worker resumes the same schedule
  rather than losing track of how many attempts have already happened.
