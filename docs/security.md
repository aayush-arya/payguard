# Security (Phase 16)

Status: implemented. A threat model covering this system's actual attack
surface, plus the two pieces of AuthN/AuthZ hardening
[docs/architecture.md](architecture.md) section 13 committed to but never
built until now: API key rotation with an overlap window, and merchant-scoped
rate limiting.

## Trust boundaries

There are exactly two ways into this system, and they are trusted
completely differently:

| Boundary | Who's allowed in | Mechanism |
|---|---|---|
| `Authorization: Bearer <key>` (all `/v1/payments`, `/v1/refunds`, `/v1/dashboard` routes) | A merchant, proving possession of their own API key | SHA-256 hash comparison against `merchants.api_key_hash` (or, during a rotation's overlap window, `previous_api_key_hash`) |
| `POST /v1/webhooks/provider` | The payment provider, proving possession of a shared HMAC secret | `packages/webhooks/security.py`: HMAC-SHA256 over `timestamp.raw_body`, constant-time compared, with a 5-minute replay-protection window (ADR-006, Phase 7) |

Nothing else is trusted for authorization on either boundary. The webhook
endpoint's own docstring states this plainly: "the webhook endpoint is
public and unauthenticated by any means except this signature. Anyone can
POST to it." IP address, headers, and TLS client certs are informational at
best — this system was designed from Phase 7 onward to never lean on any of
them for a security decision.

## API key design

- **Format**: `sk_test_<32 random bytes, url-safe base64>` (`packages/
  domain/security.py`). High entropy, no guessable structure.
- **Storage**: SHA-256 hash only, never the plaintext. `generate_api_key()`'s
  own docstring explains why a *fast* hash is the correct choice here, not
  bcrypt/argon2: those slow-hash algorithms exist to blunt brute-force
  guessing against low-entropy human-chosen secrets (passwords). A 256-bit
  random token has no guessable structure for a slow hash to protect
  against — using one would only add needless latency to every
  authenticated request without buying any real resistance a fast hash
  doesn't already provide against a token of this entropy.
- **Rotation** (new this phase, `packages/merchants/service.py`):
  `rotate_api_key()` issues a new key and moves the current one to
  `previous_api_key_hash` with a 24-hour expiry, rather than deleting it
  outright. `get_current_merchant()` (`apps/api/dependencies.py`) accepts
  either the current key or a still-valid previous one. An already-deployed
  integration keeps working through a rotation instead of failing the
  instant an operator runs `scripts/rotate_api_key.py` — the same "overlap,
  don't cut over instantly" instinct behind this codebase's outbox retry
  design (Phase 6), applied to credentials instead of events.
- **Rotation is out-of-band**, same reasoning as `scripts/seed_merchant.py`:
  merchant provisioning already has no HTTP endpoint by design (docs/
  architecture.md section 16's API list is entirely payment/refund/webhook
  operations), and self-service key rotation via the API would mean a
  compromised key could rotate *itself* to stay valid indefinitely — the
  opposite of what rotation is for.

## Tenant isolation (AuthZ)

Every payment-scoped row carries `merchant_id`, and every query path
filters by the authenticated merchant's id at the repository layer
(`packages/payments/service.py`'s `lock_payment()`, `get_payment()`,
`list_payments()`, `get_payment_detail()`) — not left to individual
endpoint handlers to remember. This phase's contribution was proving it,
not building it: every merchant-scoped endpoint now has an explicit
cross-merchant test attempting the exact attack a curious or malicious
merchant would try (read another merchant's payment/refund by guessing or
reusing its id; capture or refund another merchant's payment; check that
an aggregate endpoint's numbers never include another merchant's data):

| Endpoint | Cross-merchant test |
|---|---|
| `GET /v1/payments/{id}` | `test_merchant_cannot_read_another_merchants_payment` |
| `POST /v1/payments/{id}/capture` | `test_merchant_cannot_capture_another_merchants_payment` |
| `POST /v1/payments/{id}/refunds` | `test_merchant_cannot_refund_another_merchants_payment` |
| `GET /v1/refunds/{id}` | `test_merchant_cannot_read_another_merchants_refund` |
| `GET /v1/payments` (list), `GET /v1/payments/{id}/detail` | `test_list_payments_is_scoped_to_the_authenticated_merchant`, `test_payment_detail_is_scoped_to_the_authenticated_merchant` (Phase 13) |
| `GET /v1/dashboard/summary` | `test_dashboard_summary_excludes_other_merchants_payments` |
| `POST /v1/dashboard/reconciliation/run` | `test_reconciliation_run_endpoint_only_touches_the_calling_merchants_payments` (Phase 13) |

Every mutating case additionally confirms the attacker's request had *zero*
effect (not just a 404 response) — the target payment's status is re-read
afterward and asserted unchanged, so a bug that returned 404 while still
silently mutating the row would still be caught.

## Rate limiting

Merchant-scoped token buckets held in Redis (`packages/ratelimit/`), applied
to the three payment-mutation endpoints (create/capture/refund) — not GETs,
which a legitimate integration might poll frequently and which don't cost
this system a provider call or a settlement decision.

**Why Redis, not an in-process counter**: a counter living in the API
process's memory would let a merchant get N times the intended limit simply
by spreading requests across N horizontally-scaled replicas, each with its
own independent counter that knows nothing about the others. A shared Redis
store is what makes the limit actually mean what it says regardless of how
many API replicas are running (Phase 17 will run more than one).

**Why a Lua script, not a plain Redis `INCR`**: the check ("does this
merchant have a token left?") and the consequence ("consume one") have to
happen as a single atomic operation, for the identical reason ADR-001
requires idempotency claims to be one `INSERT` rather than a `SELECT` then
an `INSERT` — two concurrent requests each independently reading "3 tokens
left" and deciding to proceed would let both through even though only one
token's worth of capacity actually remained. Redis executes an `EVAL`'d Lua
script as one indivisible operation regardless of how many clients call
concurrently (Redis itself is single-threaded for command execution), which
is exactly the same class of guarantee this codebase gets from a single
database transaction elsewhere. `tests/concurrency/test_rate_limit_race.py`
proves it: 100 concurrent requests against a 20-token bucket let through
exactly 20, never more — the same style of proof
`tests/concurrency/test_idempotency_race.py` already does for the database
claim.

Buckets lazily refill based on elapsed wall-clock time rather than a
background job ticking every merchant's bucket, and expire themselves in
Redis once idle long enough to have fully refilled — a merchant with no
traffic costs nothing to "maintain." Configurable via `RATE_LIMIT_CAPACITY`
/ `RATE_LIMIT_REFILL_PER_SECOND` env vars, read fresh on every call rather
than frozen at process start (the first draft used a module-level constant
baked in at import time, which silently made it impossible for a test to
lower the limit without monkeypatching internal module state — fixed by
reading the environment inside the function instead, matching how every
other env-configured value in this codebase already works).

## What this system already gets right by construction, not by a Phase-16 patch

- **SQL injection**: every query in this codebase goes through SQLAlchemy's
  parameterized query builder — there is no string-concatenated SQL
  anywhere to search for, because it was never written that way from
  Phase 2 onward.
- **Double-spend / duplicate charges**: the entire premise of this project
  (idempotency claims backed by a single unique-constraint `INSERT`, Phases
  2–3) already closes the class of bug rate limiting or auth alone
  wouldn't — a legitimate but retried request is handled correctly by
  design, not merely rate-limited into being less likely to cause damage.
- **XSS**: the API returns only `application/json`, never renders HTML from
  request-controlled data. The dashboard (Phase 13) is a separate React
  app where JSX escapes interpolated values by default; nothing in it uses
  `dangerouslySetInnerHTML`.
- **Secrets in logs**: `packages/observability/logging.py`'s own docstring
  states the invariant directly — "no raw payment tokens, API keys, or
  webhook secrets are ever logged... by construction, not by a redaction
  filter bolted on afterward." Nothing in this codebase passes a secret to
  a logger; there was never a filter to bypass.

## CORS: deliberately wide open, and why that's still safe here

`apps/api/main.py` sets `allow_origins=["*"]` with `allow_credentials=False`
so the dashboard (a separate origin — the Vite dev server today, a static
build later) can call the API. This is safe specifically *because* auth is
a bearer token the browser must be explicitly given (via the dashboard's
own connect screen, stored in `localStorage`), never a cookie the browser
attaches automatically. Wide-open CORS is a real vulnerability when it's
paired with cookie-based auth (`allow_credentials=True` lets any origin's
JavaScript ride a logged-in user's session); it's a non-issue when nothing
about the request is ambient. A production deployment would still likely
narrow `allow_origins` to the dashboard's actual domain as defense in
depth, but the security property that actually matters here doesn't depend
on it.

## Explicitly out of scope for this phase

- **TLS termination, a WAF, DDoS protection at the network layer** — these
  are infrastructure concerns that belong to Phase 17 (Docker/Kubernetes)
  and Phase 18 (Terraform/cloud deployment), not application code. Rate
  limiting here protects a merchant's own quota and the provider
  integration behind it from being hammered by that merchant's own
  misbehaving client; it is not a substitute for edge-level DDoS
  mitigation, and was never meant to be.
- **A real admin/operator authentication system** for the rotation and
  seeding scripts — they run with direct database access as a trusted
  operator action (same model as every payment platform's actual merchant
  onboarding), not behind a new auth layer this phase would have had to
  invent and then immediately worry about securing itself.
- **Multi-key-per-merchant rotation** (an unlimited history of retained
  keys). The overlap-window design intentionally retains at most one
  previous key — a second rotation during an active overlap window
  discards whatever was in `previous_api_key_hash` before it. This matches
  what docs/architecture.md's security section actually described ("issuing
  a new key with an overlap window before revoking the old one") without
  building unbounded key history nothing in this project's threat model
  calls for.

## Testing

| Layer | What it proves | Where |
|---|---|---|
| Unit | Token bucket honors capacity/refill rate, never over-refills past capacity, different merchants have independent buckets | `tests/unit/test_ratelimit.py` |
| Unit | `rotate_api_key()` issues a genuinely new key, preserves the old one with a correct expiry, a second rotation discards the first-previous key | `tests/unit/test_merchants_rotation.py` |
| Integration | New key authenticates immediately; old key still works during the overlap window; old key rejected once expired; a twice-rotated key is fully retired; rotation doesn't affect other merchants | `tests/integration/test_key_rotation.py` |
| Integration | Requests within the limit succeed, requests beyond it get `429 RATE_LIMITED`, the limit is scoped per merchant, read endpoints are exempt | `tests/integration/test_rate_limiting.py` |
| Integration | Cross-merchant read/write attempts against every merchant-scoped endpoint are rejected and have zero side effect | `tests/integration/test_payment_api.py`, `test_refunds.py`, `test_dashboard.py` |
| Concurrency | 100 concurrent requests against a 20-token bucket let through exactly 20 — the Lua script's atomicity holds under real concurrent access | `tests/concurrency/test_rate_limit_race.py` |

Run everything: `pytest tests/` (requires
`docker compose up -d postgres redis` and `alembic upgrade head` first).
