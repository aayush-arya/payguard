# Final Engineering Review (Phase 20)

Twenty phases, 253 tests, ~4,966 lines of application code backed by
~4,343 lines of test code (a near 1:1 ratio — this project's tests are not
an afterthought bolted on at the end), 1,203 lines of dashboard frontend,
19 topic docs, 8 ADRs, roughly 20 commits. Every phase shipped with real
tests against a real Postgres database (never a mock), a doc explaining
what was actually built and why, and — as of Phase 19 — a green CI run
before being called done.

This document is the retrospective Phase 1 asked for without knowing it
yet: what the "10 hardest problems" list predicted actually looked like
once built, what genuinely surprised the process, what's still not
production-ready, and what a team picking this up would need to know.

## Revisiting Phase 1's "Top 10 Hardest Engineering Problems"

[docs/architecture.md section 18](architecture.md#18-top-10-hardest-engineering-problems-in-this-project)
listed these before a line of implementation code existed. All ten held up
as genuinely hard — none turned out to be easier than expected — and all
ten are now backed by a test that fails if the property stops holding, not
just a docstring asserting it does:

| # | Predicted problem | Where it actually landed |
|---|---|---|
| 1 | Exactly-once under concurrent identical requests | A single unique constraint (Phase 2), proven at the HTTP boundary with 100 real concurrent requests (Phase 3) — still the property Phase 16's rate limiter and Phase 19's CI both had to be built *around*, not against |
| 2 | The unknown-outcome problem | Reconciliation (Phase 10) — later reused twice: as the dashboard's on-demand trigger (Phase 13) and as the resolution mechanism chaos-injected failures rely on (Phase 14) |
| 3 | Transaction boundaries excluding network calls | The outbox pattern (Phase 6) — its one deliberate lock/network-call tradeoff is documented, not hidden |
| 4 | Double refunds under concurrent partial refunds | Row lock + balance check (Phase 8) — a real concurrency bug here (`REFUND_PENDING` transition logic) was caught and fixed *by the tests written to prove the invariant*, not found later |
| 5 | Webhook dedup/ordering | Unique constraint on `(provider_name, provider_event_id)` + idempotent effect application (Phase 7), stress-tested at 20 concurrent duplicate deliveries |
| 6 | A provably-safe state machine | `domain.state_machine`'s actor-restricted transition table (Phase 2) — every subsequent phase that adds a new transition (reconciliation, chaos resolution) had to go through it, not around it |
| 7 | Deadlock avoidance across entry points | Consistent lock ordering + short critical sections, most visibly in the outbox worker's documented "release the lock before the slow network call" tradeoff |
| 8 | Retry classification | `_FAILURE_CLASSIFICATION` (Phase 3) feeding both the outbox retry policy (Phase 6) and reconciliation's resolution logic (Phase 10) from one source of truth |
| 9 | Ledger balance under partial failure | Double-entry writes tied to specific settlement events, not generic transitions (Phase 9) — `global_ledger_balance()` is reused as a real assertion in Phase 14's chaos test, not just Phase 9's own tests |
| 10 | Proving all of the above under load | Concurrency tests since Phase 2, generalized twice more: Phase 14's chaos provider (random rather than hand-picked failure) and Phase 15's k6 load tests (a real load generator's connection pool and OS scheduling, not one Python event loop) |

## What actually surprised the process

Not the ten predicted problems — they were hard exactly as predicted, and
solving them took the effort the list implied it would. What surprised
this project was almost entirely in the *later*, less glamorous phases,
where "should be routine" turned out not to be:

- **Observability's own tooling had a real bug in it** (Phase 12): OpenTelemetry's global `TracerProvider` can only be set once per process, which silently broke test isolation until `get_tracer()` was redesigned around a lazy-resolving proxy instead of the OTel global registry. Caught only because tests were written for the tracing module itself, not just wired in and trusted.
- **A real routing bug surfaced only by manually driving the browser** (Phase 13): the dashboard's connect screen authenticated successfully but never told the router to navigate away from `/connect`. No amount of `tsc`/build/lint would have caught this — it required actually clicking through the UI.
- **A load test's own report tooling had the bug, not the system under test** (Phase 15): the first parser draft assumed a JSON shape k6 v2 doesn't use, and failed by silently printing zeros rather than erroring — arguably worse than a crash, and a reminder that a monitoring/reporting layer is code too, with its own bug surface.
- **Two independently-correct features conflicted** (Phase 16): the new rate limiter legitimately started rejecting the pre-existing 100-concurrent-request idempotency tests mid-burst. Neither feature was wrong; a test written before rate limiting existed needed an explicit scope adjustment once it did. This is the kind of interaction that only appears when a system accumulates enough real features to step on each other, which single-feature unit tests structurally cannot surface.
- **This environment's own limits became part of the honest record** (Phases 17–18): a `kind` cluster couldn't be created (DNS resolution to Docker Hub blocked in this specific sandbox, while Docker itself pulled every other image fine), and Terraform was never applied against a real AWS account because none exists for this project to authorize spending on. Both gaps are stated directly in docs/deployment.md and docs/terraform.md rather than glossed over — "verified" means verified, and where it doesn't, the doc says so.
- **CI's own first real run caught two bugs neither local dev nor 253 passing local tests had surfaced** (Phase 19): `ruff format --check` failed because the lint job's unpinned `pip install ruff` resolved to a newer version than local development had actually validated against — one that formats fenced Python code blocks in Markdown differently — and *every* `apps.*`-importing test failed with `ModuleNotFoundError` because the workflow ran a bare `pytest` instead of `python -m pytest` (only the latter puts the current directory on `sys.path`, which is what makes `apps.api`/`apps.worker` importable at all locally). Diagnosing the first bug also surfaced a second, quieter one: local `ruff format --check` had itself been silently passing against a stray system-Python `ruff` install shadowing this project's own `.venv` version on `PATH`. None of these were hypothetical "CI might catch this" concerns — they were real, and CI caught all three in its first ten minutes of existing.

## What is genuinely production-ready, as built

- The idempotency/concurrency/state-machine/ledger core (Phases 2–3, 8–9) —
  proven under real concurrent load, not just unit-tested in isolation.
- Observability (Phase 12) and security (Phase 16) as *designs* — structured
  logging, metrics, tracing, rate limiting, and key rotation are all real,
  tested code, not sketches.
- The CI pipeline (Phase 19) — it runs for real on every push against this
  project's actual repository.

## What is explicitly not production-ready, and why that's honest rather than a gap

- **No real payment provider.** `MockProvider` (Phase 4) is deterministic
  by design — real provider adapters (Stripe, Adyen, whoever) were always
  out of scope; the `PaymentProvider` protocol exists specifically so
  writing one is an adapter-shaped problem, not an architecture change.
- **No real TLS termination, WAF, or DDoS protection** — Phase 16's threat
  model names these as infrastructure-layer concerns Phases 17/18 would
  own, and Phase 17/18's own docs are explicit that the ALB listener here
  is plaintext HTTP because ACM needs a real domain this project doesn't
  have, and ECS/RDS were never applied against a billed AWS account.
- **Single NAT gateway, single-node Redis, one-AZ-tolerant-but-not-region-tolerant
  design** — every one of these is a stated cost/scope tradeoff in
  docs/terraform.md and docs/deployment.md, not a silently-accepted
  limitation discovered later.
- **This dev environment's own constraints leaked into what could be
  verified** — Docker-on-Windows networking overhead is a real, measured
  contributor to Phase 15's latency numbers (docs/load-testing.md), and
  the `kind` cluster / real AWS apply gaps above are two more. None of
  these are hidden; docs/load-testing.md, docs/deployment.md, and
  docs/terraform.md each name their own environment-specific limits
  directly.

## If a team picked this up tomorrow

In rough priority order:

1. **Write a real provider adapter** against the `PaymentProvider` protocol
   — the architecture was built for this from Phase 4 onward; it's the
   single highest-leverage next step to make this system take real traffic.
2. **Apply Phase 18's Terraform against a real, billed AWS account**, add
   the remote-state backend that's already commented in and ready, and put
   a real domain + ACM cert behind the ALB.
3. **Re-run Phase 17's Kubernetes manifests against a real cluster**
   (`kind`, a managed EKS cluster, or Phase 18's own eventual EKS module)
   to close the one verification gap this environment couldn't close.
4. **Revisit Phase 16's CORS and rate-limit defaults** for the specific
   production domain and traffic pattern, per docs/security.md's own
   "defense in depth" note.
5. **Size RDS/ElastiCache for real load** — docs/terraform.md's
   `db.t4g.micro`/`cache.t4g.micro` defaults are explicitly named as
   reference-scale, not production-scale.

## Closing note

Every phase in this project shipped the same way: build it, test it
against something real, write down what was actually true (including what
didn't work on the first attempt), then move to the next phase. That
discipline is what this final document is summarizing, not introducing —
the honesty above about `kind`'s DNS failure or Terraform never being
applied is the same standard docs/observability.md held itself to back in
Phase 12, just applied one more time, to the whole project at once.
