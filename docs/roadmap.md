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
| 3 | Payment API: create/status/capture | Not started |
| 4 | Provider abstraction + MockProvider failure modes | Not started |
| 5 | Idempotency + concurrency implementation and tests | Not started |
| 6 | Transactional outbox + worker | Not started |
| 7 | Webhook processing (security, dedup, async apply) | Not started |
| 8 | Refunds (partial/full, concurrency-safe) | Not started |
| 9 | Double-entry ledger + balance invariant | Not started |
| 10 | Reconciliation engine | Not started |
| 11 | Risk/fraud rule engine | Not started |
| 12 | Observability: OpenTelemetry, Prometheus, structured logs | Not started |
| 13 | React/TS/Tailwind dashboard | Not started |
| 14 | Chaos/failure simulator + demo scenarios | Not started |
| 15 | Load testing (k6) | Not started |
| 16 | Security: threat model, authn/authz hardening, rate limiting | Not started |
| 17 | Docker + Kubernetes | Not started |
| 18 | Terraform / optional AWS deployment | Not started |
| 19 | CI/CD (GitHub Actions) | Not started |
| 20 | Final engineering review | Not started |

Phase 1 deliverables live in [`architecture.md`](architecture.md) and
[`adr/`](adr). Nothing beyond documentation is implemented yet — no application code,
no migrations, no Docker Compose file — by design, so that Phase 2 starts from an
agreed contract rather than code that predates the design discussion.
