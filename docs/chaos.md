# Chaos / Failure Simulator (Phase 14)

Status: implemented. `ChaosProvider` (`packages/providers/chaos.py`) wraps
any `PaymentProvider` and probabilistically corrupts what the *caller*
sees, so the system's UNKNOWN-handling and reconciliation machinery gets
exercised by a seeded random process instead of only hand-picked scenario
tokens. `docs/architecture.md` section 9 anticipated this ("MockProvider
accepts a per-request scenario hint **or merchant/global chaos
configuration**") — this phase builds the second half of that sentence.

## How it works

`ChaosProvider.authorize()` always delegates to the wrapped provider
first, then — with probability `unknown_rate` — overwrites the
*caller-visible* result with `UNKNOWN`, discarding nothing the wrapped
provider recorded internally. This mirrors `MockProvider`'s own
`pm_demo_timeout` scenario (a token-triggered version of exactly this
idea, built in Phase 3/10), generalized from "triggered by a magic
substring" to "triggered by a weighted coin flip with a reproducible
seed." Because the wrapped provider's own bookkeeping is untouched,
reconciliation's `get_payment_status_by_idempotency_key()` call still
finds the truth — chaos corrupts what the merchant's request sees, never
what the system can still discover by asking.

A separate `slow_rate` independently injects artificial latency before
any call returns (authorize/capture/refund), exercising the observability
latency histograms and giving a demo something visibly slow to point at,
without touching outcome correctness at all.

```python
chaos = ChaosProvider(MockProvider(), ChaosConfig(unknown_rate=0.35, seed=1))
```

Same seed, same sequence of corrupt/no-corrupt decisions — a chaos run is
reproducible, not just "random and hope it demonstrates something."

## Deliberate scope boundary: authorize() only

Two extensions were considered and deliberately left out:

- **Corrupting capture()/refund() outcomes.** `MockProvider.refund()` has
  no `UNKNOWN` branch at all — `refund_payment()`
  (`packages/payments/service.py`) treats anything that isn't `SUCCEEDED`
  as `FAILED`. Corrupting refund responses would exercise a code path that
  was never designed to receive `UNKNOWN`, not a real resilience story.
  `capture()` *happens* to resolve correctly under corruption (it always
  truly succeeds in `MockProvider`; reconciliation would rediscover that
  via the same idempotency-key lookup an authorize-corruption uses) — but
  relying on that coincidence felt like the wrong thing to build a
  documented chaos surface on top of.
- **Raising raw exceptions from `authorize()`.** `create_payment()` has no
  handling path for a provider call raising outright — it fails the
  idempotency claim and forces the caller to retry with a fresh key. That
  is a real, valid failure mode, but a *different* one from what this
  phase demonstrates: the outcome-classification and reconciliation
  machinery already built in Phases 3, 6, and 10.

## `scripts/demo_scenarios.py`

A narrated, runnable walkthrough — not a test, no assertions — proving
the resilience story end to end against the real FastAPI app, real
routing/dependency-injection, and a real Postgres database (same
in-process ASGI transport the test suite itself uses, so nothing here is
a mocked substitute for what the API actually does):

| Demo | What it shows |
|---|---|
| 1 | Happy path: create → authorize → capture → `SUCCEEDED` |
| 2 | Declined payment: `PERMANENT` failure, correctly never retried |
| 3 | Response lost in transit: `UNKNOWN` → reconciliation asks the provider directly → `SUCCEEDED`, never a blind retry |
| 4 | (narrated, not re-run) points to `tests/concurrency/test_webhook_race.py`'s 20-concurrent-duplicate-delivery proof — re-implementing HMAC signing here would just be a worse copy of a test that already exists |
| 5 | Chaos burst: 20 concurrent payments through a seeded `ChaosProvider`, then the same on-demand reconciliation trigger the dashboard exposes, resolving every corrupted payment |

Run it: `python scripts/demo_scenarios.py` (requires
`docker compose up -d postgres redis` and `alembic upgrade head` first,
same as every other script in this repo).

## Testing

| Layer | What it proves | Where |
|---|---|---|
| Unit | Corruption rate is honored (0.0 = passthrough, 1.0 = always corrupted), corruption never destroys the true outcome, same seed → same decision sequence, `slow_rate` actually delays, `get_payment_status*` is never corrupted | `tests/unit/test_chaos_provider.py` |
| E2E | A 30-payment batch with real HTTP requests and a live database, ~40% corrupted: every payment reaches a real terminal status (never stuck `UNKNOWN`), attempt/transaction counts match exactly what each payment's own history explains (no reconciliation double-processing), and the ledger stays globally balanced throughout | `tests/e2e/test_chaos_resilience.py` |

A genuine finding surfaced while writing the e2e test, not a bug: a
successfully-authorized payment that chaos left alone correctly stays
`PROCESSING`, not `SUCCEEDED` — this system only reaches `SUCCEEDED` via
an explicit `capture()` call (docs/payments.md), and the chaos test never
calls capture. The first draft of the test asserted every payment would
end up `SUCCEEDED` or `FAILED` and failed loudly against real `PROCESSING`
rows — a useful reminder that even a resilience test's own assumptions
need to match the state machine, not just what would be convenient to
assert.

Run everything: `pytest tests/` (requires
`docker compose up -d postgres redis` and `alembic upgrade head` first).
