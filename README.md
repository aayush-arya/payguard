# PayGuard

A production-grade, idempotent payment gateway backend built to demonstrate real
distributed-systems engineering: safe payment processing under retries, concurrency,
network failure, worker crashes, and unpredictable payment-provider behavior.

PayGuard is **not** a CRUD app, a Stripe wrapper, or a payment form. It is a small but
serious payment infrastructure platform focused on one central problem:

> How do we guarantee that a payment operation is processed safely and consistently
> when clients retry requests, requests arrive concurrently, networks fail, workers
> crash, and external payment providers respond unpredictably?

No real money, real card data, or real payment credentials are used anywhere in this
project. All provider integrations run against a deterministic mock payment provider
for local development and testing.

## Status

This repository is being built in phases. See [`docs/architecture.md`](docs/architecture.md)
for the full system design and [`docs/roadmap.md`](docs/roadmap.md) for phase-by-phase
progress.

- [x] Phase 1 — Architecture
- [x] Phase 2 — Domain + Database
- [ ] Phase 3 — Payment API
- [ ] Phase 4 — Provider abstraction
- [ ] Phase 5 — Idempotency + concurrency
- [ ] Phase 6 — Transactional outbox
- [ ] Phase 7 — Webhooks
- [ ] Phase 8 — Refunds
- [ ] Phase 9 — Ledger
- [ ] Phase 10 — Reconciliation
- [ ] Phase 11 — Risk engine
- [ ] Phase 12 — Observability
- [ ] Phase 13 — Dashboard
- [ ] Phase 14 — Chaos/failure testing
- [ ] Phase 15 — Load testing
- [ ] Phase 16 — Security
- [ ] Phase 17 — Docker/Kubernetes
- [ ] Phase 18 — Terraform/Cloud
- [ ] Phase 19 — CI/CD
- [ ] Phase 20 — Final engineering review

## Documentation

| Doc | Purpose |
|---|---|
| [docs/architecture.md](docs/architecture.md) | System architecture, diagrams, ERD, state machine, concurrency & idempotency strategy |
| [docs/adr/](docs/adr) | Architecture Decision Records for the eight major design decisions |
| [docs/database.md](docs/database.md) | Implemented schema, idempotency claim protocol, state machine, and test coverage (Phase 2) |
| [docs/roadmap.md](docs/roadmap.md) | Phase-by-phase development roadmap |

## Running locally

```bash
docker compose up -d postgres redis
cp .env.example .env
python -m venv .venv && . .venv/Scripts/activate  # or source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
alembic upgrade head
pytest tests/
```

Further docs (`database.md`, `idempotency.md`, `concurrency.md`, `webhooks.md`,
`reconciliation.md`, `security.md`, `observability.md`, `testing.md`,
`deployment.md`, `failure-modes.md`) will be added as their corresponding phases land,
so they describe real, built behavior rather than aspirational design.

## License

Personal portfolio project. No license granted for reuse yet.
