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
- [x] Phase 3 — Payment API
- [x] Phase 4 — Provider abstraction (MockProvider only; real adapters deferred)
- [x] Phase 5 — Idempotency + concurrency (built/tested in Phase 2, exercised end-to-end in Phase 3)
- [x] Phase 6 — Transactional outbox
- [x] Phase 7 — Webhooks
- [x] Phase 8 — Refunds
- [x] Phase 9 — Ledger
- [x] Phase 10 — Reconciliation
- [x] Phase 11 — Risk engine
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
| [docs/payments.md](docs/payments.md) | Payment API design decisions: authorize/capture semantics, MockProvider, test coverage (Phase 3) |
| [docs/outbox.md](docs/outbox.md) | Outbox worker design: retry/backoff, dead-lettering, the one deliberate lock/network-call tradeoff in the codebase (Phase 6) |
| [docs/webhooks.md](docs/webhooks.md) | Webhook threat model, signature/replay protection, dedup, and how effect-application wires into the outbox worker (Phase 7) |
| [docs/refunds.md](docs/refunds.md) | Refund balance invariant, a real concurrency bug the tests caught and how it was fixed, idempotency reuse (Phase 8) |
| [docs/ledger.md](docs/ledger.md) | Double-entry ledger design, why writes are tied to specific events not generic transitions, DB-level immutability trigger (Phase 9) |
| [docs/reconciliation.md](docs/reconciliation.md) | Resolving UNKNOWN payments by asking the provider directly, idempotency-key lookup, Demo 3 end to end (Phase 10) |
| [docs/risk.md](docs/risk.md) | Deterministic rule-based risk signals, scoring, and where BLOCK plugs into payment creation (Phase 11) |
| [docs/roadmap.md](docs/roadmap.md) | Phase-by-phase development roadmap |

## Running locally

```bash
docker compose up -d postgres redis
cp .env.example .env
python -m venv .venv && . .venv/Scripts/activate  # or source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
alembic upgrade head
pytest tests/

# try it
python scripts/seed_merchant.py "Demo Merchant"   # prints an API key, shown once
uvicorn apps.api.main:app --reload                # http://localhost:8000/docs
python apps/worker/main.py                        # separate terminal: processes outbox events
```

Further docs (`idempotency.md`, `concurrency.md`, `reconciliation.md`, `security.md`,
`observability.md`, `testing.md`, `deployment.md`, `failure-modes.md`) will be added
as their corresponding phases land, so they describe real, built behavior rather than
aspirational design.

## License

Personal portfolio project. No license granted for reuse yet.
