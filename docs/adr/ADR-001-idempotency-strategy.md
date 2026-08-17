# ADR-001: Idempotency Strategy

## Status
Accepted

## Problem
Merchant clients retry `POST /v1/payments` for reasons unrelated to whether the first
attempt actually succeeded: client timeouts, load-balancer retries, mobile network
drops. The system must guarantee that N retries of the same logical request produce
exactly one payment operation, and must reject retries that reuse a key with a
genuinely different payload rather than silently accepting either version.

## Options considered

1. **Application-level "check then insert."** Read whether a key exists; if not,
   proceed to create the payment. Simple, but a textbook TOCTOU race: two concurrent
   requests can both observe "not present" before either writes. Rejected — this is
   exactly the bug class the project exists to solve, not something to allow.
2. **Redis `SETNX` as the idempotency lock.** Fast, but Redis is not the system of
   record for money in this project, and a Redis failure/restart could silently drop
   the lock while a payment row already exists in Postgres, reopening the race. Usable
   for ancillary coordination (rate limits), rejected as the source of truth for
   payment uniqueness.
3. **Database unique constraint + `INSERT ... ON CONFLICT DO NOTHING`, scoped per
   merchant, storing a request fingerprint and eventual response.** Chosen. The
   uniqueness guarantee is enforced by the same engine that holds the payment data, in
   the same transaction, so there is no cross-system window where the two can
   disagree.

## Decision
Use a `idempotency_keys` table with `UNIQUE (merchant_id, idempotency_key)`. Claim a
key via `INSERT ... ON CONFLICT DO NOTHING RETURNING id` inside the same transaction
that creates the `payment_intents` row. Store a SHA-256 fingerprint of the canonical
request body alongside the key; a reused key with a mismatched fingerprint is rejected
with `409 IDEMPOTENCY_KEY_REUSED` before any payment row is touched. Store the final
HTTP response (status + body) on the row once the operation completes, and replay it
verbatim for subsequent requests with a matching key + fingerprint.

## Tradeoffs
- Every payment-creating endpoint requires a mandatory `Idempotency-Key` header; there
  is no "fire and forget" mode. This is intentional friction — it is the API surface
  that makes the safety guarantee possible.
- A `PENDING` row for a request whose process crashed before completing needs an
  explicit staleness policy (bounded by `locked_at`), otherwise a crashed request could
  wedge that key forever. This is handled by treating a sufficiently stale `PENDING`
  row as safe to reclaim, while relying on the state machine (not the idempotency row)
  as the actual authority on whether a provider charge happened, since that is the
  fact that actually matters financially.
- Per-merchant scoping of keys means the API must always know the authenticated
  merchant before touching the idempotency table — auth is a hard prerequisite of the
  idempotency layer, not a separate concern layered on top.

## Failure modes
- **Both requests arrive in the same millisecond**: the unique constraint resolves the
  race at the database level; the loser reads back the winner's committed row.
- **Process crashes after claiming the key but before creating the payment row**: the
  row stays `PENDING`; retried requests are told to wait or are handled per the
  staleness policy above; no duplicate payment can be created because the key is still
  claimed.
- **Client retries with a different amount by mistake**: rejected outright, no payment
  created or mutated under the reused key.

See [`docs/architecture.md`](../architecture.md#4-idempotency-design) for the full
claim protocol and [ADR-002](ADR-002-postgresql-locking-strategy.md) for how this
composes with row-level locking on the payment itself.
