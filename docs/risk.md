# Risk / Fraud Engine (Phase 11)

Status: implemented. A deterministic, explainable, rule-based risk engine
(product brief section 20) wired into payment creation — **not** a production
fraud model, and never claimed to be one.

## Signals

| Signal | Weight | Trigger |
|---|---|---|
| `VERY_LARGE_AMOUNT` | 50 | `amount_minor >= 2,000,000` ($20,000) |
| `LARGE_AMOUNT` | 20 | `amount_minor >= 500,000` ($5,000) (only one amount signal fires — the higher tier supersedes the lower, they don't stack) |
| `REPEATED_FAILURES` | 40 | ≥3 `DECLINED` attempts by this merchant in the last 5 minutes (card-testing pattern) |
| `HIGH_VELOCITY` | 30 | ≥5 payments created by this merchant in the last 5 minutes |
| `HIGH_RISK_IP` | 35 | `customer_ip` falls in an RFC 5737 documentation-only range (`198.51.100.0/24`, `203.0.113.0/24`) |
| `BILLING_SHIPPING_COUNTRY_MISMATCH` | 25 | `billing_country != shipping_country`, both supplied |

Score is the sum of every signal that fires, banded into a level:

```
score >= 100  -> BLOCK
score >=  60  -> HIGH
score >=  30  -> MEDIUM
score <   30  -> LOW
```

These weights and thresholds are not calibrated against real fraud data —
there is none to calibrate against in a project with no real transactions.
They exist to make the banding legible in tests and demos, not to represent
a defensible production risk model.

## Why `HIGH_RISK_IP` uses RFC 5737 ranges

`198.51.100.0/24` and `203.0.113.0/24` are permanently reserved for
documentation and testing — no real customer traffic will ever legitimately
originate from them. That makes them a safe, deterministic stand-in for "a
known-bad IP" without needing a real IP reputation service or risking a false
positive against a real address. A production system would call an actual
IP intelligence provider here; this project demonstrates where that call
would go, not a working substitute for it.

## Where it plugs into the payment flow

`assess_payment_risk()` runs in `create_payment()`
(`packages/payments/service.py`) right after the payment moves to
`PROCESSING`, **before** `provider.authorize()` is ever called. Every
assessment — regardless of level — is recorded to `audit_logs`
(`actor="RISK_ENGINE"`, `action="payment.risk_assessed"`), giving a complete,
queryable history of every risk decision made, not just the ones that
blocked something.

`BLOCK` is the only level that changes behavior: the payment moves straight
to `FAILED` (via the same `PROCESSING -> FAILED` transition a provider
decline uses) and **`provider.authorize()` is never called** — no
`payment_attempts` row, no `provider_transactions` row, because the system
genuinely never asked. `LOW`/`MEDIUM`/`HIGH` are purely observational in
this phase: recorded, not acted on. A production system would likely route
`HIGH` to manual review or step-up authentication (3DS) rather than a binary
allow/block, but that's out of scope for what this phase demonstrates.

## Request fields

`POST /v1/payments` accepts three new, entirely optional fields:
`billing_country`, `shipping_country`, `customer_ip`. Omitting all three
simply means those signals never fire — nothing requires them. If
`customer_ip` isn't supplied, the API falls back to the actual HTTP
connection's remote address (`request.client.host`) rather than leaving the
signal permanently dark, so the IP-based check still has *something* to
evaluate even for merchants that don't pass it explicitly (though the value
of that fallback in a real deployment depends entirely on trusting the
network path — a merchant proxying requests would present its own IP, not
the shopper's).

## Testing

| Layer | What it proves | Where |
|---|---|---|
| Unit | Amount tiering (only one fires, not both), country mismatch requires both fields present, high-risk IP matching, and every `RiskLevel` threshold boundary | `tests/unit/test_risk_engine.py` |
| Integration | Velocity and repeated-failure signals against real payment history, every assessment reaching `audit_logs`, multiple weak signals compounding into a `BLOCK`, and that a blocked payment creates zero `payment_attempts` rows | `tests/integration/test_risk_engine.py` |

Run everything: `pytest tests/` (requires `docker compose up -d postgres redis` and
`alembic upgrade head` first).
