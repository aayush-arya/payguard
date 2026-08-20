# Development Roadmap

Work proceeds in phases. Each phase is expected to land with its own tests, and,
where it introduces new user-facing behavior, its own documentation update. Phases
are not implemented out of order — later phases depend on invariants established by
earlier ones (e.g. the outbox pattern in Phase 6 depends on the transaction-boundary
discipline established in Phase 2/3).

| Phase | Scope | Status |
|---|---|---|
| 1 | Architecture: diagrams, ERD, state machine, ADRs, roadmap | Done |
| 2 | Domain models, migrations, constraints, state machine implementation, idempotency storage | Done |
| 3 | Payment API: create/status/capture | Done |
| 4 | Provider abstraction + MockProvider failure modes | Done (MockProvider only; Provider A/B real adapters deferred -- nothing depends on them yet) |
| 5 | Idempotency + concurrency implementation and tests | Substantially done -- claim protocol built/tested in Phase 2, exercised end-to-end at the HTTP layer with a 100-concurrent-request test in Phase 3 |
| 6 | Transactional outbox + worker | Done |
| 7 | Webhook processing (security, dedup, async apply) | Done |
| 8 | Refunds (partial/full, concurrency-safe) | Done |
| 9 | Double-entry ledger + balance invariant | Done |
| 10 | Reconciliation engine | Done |
| 11 | Risk/fraud rule engine | Done |
| 12 | Observability: OpenTelemetry, Prometheus, structured logs | Done |
| 13 | React/TS/Tailwind dashboard | Done |
| 14 | Chaos/failure simulator + demo scenarios | Done |
| 15 | Load testing (k6) | Done |
| 16 | Security: threat model, authn/authz hardening, rate limiting | Done |
| 17 | Docker + Kubernetes | Done |
| 18 | Terraform / optional AWS deployment | Done (validated, not applied -- no AWS account in this project) |
| 19 | CI/CD (GitHub Actions) | Done |
| 20 | Final engineering review | Done |
| 21 | Premium dashboard redesign (visual system, real-time shell, mock-data-isolated pages) | Done |
| 22 | Render deployment blueprint (free-tier managed Postgres/Redis + Docker services) | Blueprint written, not yet applied (no Render account in this project) |

Phase 1 deliverables live in [`architecture.md`](architecture.md) and
[`adr/`](adr). Nothing beyond documentation is implemented yet — no application code,
no migrations, no Docker Compose file — by design, so that Phase 2 starts from an
agreed contract rather than code that predates the design discussion.
