# Dashboard (Phase 13)

Status: implemented. A React + TypeScript + Tailwind merchant dashboard
(product brief section 16) that is deliberately a thin consumer of the API,
not a second product — every action it takes is a call to an endpoint that
already existed for Phase 3-12's own reasons, plus four small additions this
phase needed and nothing more.

## What it is, and what it deliberately isn't

The dashboard authenticates as a merchant using the same `pk_test_...`/
`sk_test_...` API key every other client uses — there is no separate
dashboard login, session, or user model. The key is entered once on a
connect screen, verified against a real endpoint (not just format-checked),
and kept in `localStorage`; every request from then on carries it as a
bearer token exactly like `curl` or a server integration would. This is a
deliberate simplification, not an oversight: the brief's own tradeoff table
says the dashboard's job is "consumer of the API," and building merchant
user accounts, sessions, or SSO would be inventing a second product with its
own security surface for a demo tool.

## The public demo key

`scripts/seed_demo_merchant.py` seeds one merchant with a fixed, publicly-known
API key, and the connect screen (`frontend/src/pages/Connect.tsx`) shows that
key directly with a one-click "Try the demo" button — so anyone opening the
dashboard can explore it immediately, without running a script or asking
anyone for credentials first. This is the one deliberate exception to
`scripts/seed_merchant.py`'s own rule that an API key is a secret shown once
and never displayed again: a demo merchant that only ever touches
`MockProvider` and fake money is exactly the case where a fixed, public key
is correct, and a real merchant's key is exactly the case where it isn't.
The seed script is idempotent — safe to run on every app start without
creating duplicate demo merchants or rotating the key out from under anyone
who already has it saved.

## New backend surface (four endpoints, all additive)

No existing endpoint's behavior changed. Four read/aggregate endpoints were
added purely because the dashboard needed them and nothing before it did:

| Endpoint | Purpose |
|---|---|
| `GET /v1/payments` | Merchant-scoped, paginated, optional `status` filter, newest-first |
| `GET /v1/payments/{id}/detail` | The payment plus every attempt/event/refund/ledger entry that explains its current state, in one round trip |
| `GET /v1/dashboard/summary` | Aggregate counts-by-status and settled/refunded volume for the landing page |
| `POST /v1/dashboard/reconciliation/run` | The on-demand reconciliation trigger ADR-008 always described ("dashboard button, demo scenario") but never had a caller for until now |

`run_reconciliation_pass()` (`packages/reconciliation/service.py`) gained an
optional `merchant_id` filter to support the last one — passing it scopes
both which payments get reconciled *and* which reports come back, so one
merchant's dashboard button can never sweep in or report on another
merchant's `UNKNOWN` payments. The default (`None`, unchanged) still
reconciles system-wide, which is what `scripts/run_reconciliation.py`'s
operational entrypoint continues to use.

`CORSMiddleware` was added to `apps/api/main.py`, open (`allow_origins=["*"]`,
`allow_credentials=False`). This is safe specifically *because* auth is a
bearer token, never a cookie — there's nothing ambient for a hostile origin
to ride on, unlike a cookie-based session where wide-open CORS plus
credentialed requests would be a real CSRF-adjacent hole. A real deployment
would still narrow `allow_origins` to the dashboard's actual origin(s); this
is the honest state for local development.

## Frontend structure

```
frontend/
├── src/
│   ├── lib/
│   │   ├── api.ts          # typed fetch wrapper, one function per endpoint
│   │   ├── auth.tsx         # API key context, localStorage-backed
│   │   ├── useApiQuery.ts   # minimal fetch-on-mount hook (no React Query --
│   │   │                     this app has no need for its cache/retry machinery)
│   │   ├── mockData.ts      # isolated mock layer -- see "Premium redesign" below
│   │   └── types.ts, format.ts
│   ├── components/
│   │   ├── ui/               # design system: GlassCard, MetricCard, StatusBadge,
│   │   │                       TrendIndicator, DataTable bits, ChartCard, Timeline,
│   │   │                       Modal, Skeleton, EmptyState/ErrorState, Toast,
│   │   │                       AmbientBackground
│   │   ├── shell/             # Sidebar, TopBar, CommandPalette (app chrome)
│   │   ├── Layout.tsx, NewPaymentModal.tsx, RefundModal.tsx
│   └── pages/                # Connect, DashboardHome, PaymentsList, PaymentDetail,
│                                Reconciliation, RiskAndFraud, Webhooks, ProviderHealth,
│                                ComingSoon
```

## Premium redesign (Phase 21)

Status: implemented. The dashboard's visual layer was rebuilt into a dark,
glassmorphic "fintech infrastructure" aesthetic (Framer Motion, Recharts,
`cmdk` command palette, a canvas particle background), without touching any
backend behavior and without regressing the "thin consumer of the API"
principle above -- every page that shows real data still gets it from the
same four endpoints (plus the pre-existing payment/refund endpoints); the
redesign only changed how that data is presented.

**Design system.** `components/ui/` holds the reusable primitives (`GlassCard`,
`MetricCard`, `StatusBadge`, `TrendIndicator`, `ChartCard`, `Timeline`,
`Modal`, `Skeleton`/`SkeletonRow`/`SkeletonCard`, `EmptyState`/`ErrorState`,
a toast system) driven by CSS custom properties defined once in `index.css`
and mirrored into Tailwind's `@theme`. Pages compose these rather than
hand-styling their own cards and tables, so the visual language stays
consistent without being duplicated per page.

**App shell.** `components/shell/` adds a collapsible `Sidebar` (a static
column on desktop, an off-canvas drawer with a backdrop below the `lg`
breakpoint -- one component for both, not two implementations that could
drift), a `TopBar` with a real `⌘K`/`Ctrl+K` command palette, and
`CommandPalette` itself, which searches live payment data via the existing
`listPayments()` call -- it is not a mock search index.

**Mock data is isolated and labeled, per an explicit brief requirement.**
Three pages -- Risk & Fraud, Webhooks, and Provider Health -- render UI for
backend surfaces that don't exist yet. Rather than scatter fabricated
numbers across components, every mock value comes from one file,
`lib/mockData.ts`, and each exported function carries a comment naming the
real endpoint that would replace it (e.g. `mockProviderHealth()` documents
that it stands in for a future per-provider `/v1/providers/health`
aggregate). Each of those three pages also says so in its own UI copy, not
just in a code comment -- a viewer doesn't have to read source to know which
numbers are illustrative. Every other page (Overview, Payments, Payment
Detail, Reconciliation) is unchanged in this respect: 100% real API data, as
it always was.

**The Idempotency Inspector** (`PaymentDetail.tsx`) is the one place the
temptation to fabricate was strongest -- the brief asked for a visual "100
requests → 1 payment" story, and no endpoint returns 100 synthetic request
records. It was built from what a given payment's real data actually proves
instead: its real `attempts.length` (the idempotency claim protocol
guarantees this is 1 regardless of retry count) and a real ledger-balance
check, with the "100 concurrent requests" framing presented as an
illustration of the guarantee and captioned with a pointer to the test that
actually exercises it at that scale, `tests/concurrency/test_payment_api_race.py`.
Nothing in the inspector reports a number that isn't real for that specific
payment.

**Responsiveness and motion.** The shell has no horizontal overflow down to
a 375px viewport (verified via `document.documentElement.scrollWidth` ===
`clientWidth`) -- the sidebar collapses to an off-canvas drawer below `lg`
and every data table sits inside an `overflow-x-auto` wrapper rather than
forcing the page to scroll sideways. `AmbientBackground` and Framer Motion
transitions both respect `prefers-reduced-motion`, pause work on a hidden
tab (`document.visibilitychange`), and cap device-pixel-ratio on the canvas
to keep the particle field cheap.

Every demo action (create/capture/refund) goes through the same
`Idempotency-Key` discipline as any other client -- `lib/api.ts` generates a
fresh `crypto.randomUUID()` per mutating call, never reuses one across
retries. Creating a payment offers the same scenario tokens
(`pm_demo_declined`, `pm_demo_timeout`, ...) MockProvider has always
supported (docs/architecture.md, `packages/providers/mock.py`) with a
uniqueness suffix appended, so the dashboard can walk through every demo
scenario -- including Demo 3's timeout → reconciliation path -- without a
terminal.

## A real bug the manual browser pass caught

The connect screen originally called `connect(apiKey)` on success and
stopped -- nothing told the router to leave `/connect`. `RequireAuth`
(wrapping the authenticated routes) only redirects the *other* direction,
unauthenticated → `/connect`; there was no corresponding "authenticated,
currently on `/connect`" case telling it to leave. The result: a correct API
key would authenticate successfully (confirmed by a real `200` from
`GET /v1/dashboard/summary`) and silently leave the user staring at the
connect form. Fixed with an explicit `navigate('/', { replace: true })`
after `connect()` succeeds (`src/pages/Connect.tsx`). This is exactly the
kind of bug type-checking and a clean build can't catch -- the code was
type-correct and rendered without error, it just never told the router to
move. Caught by manually driving the golden path in a real browser (connect
→ create → capture → refund → reconciliation), not by `tsc` or `vite build`
passing.

## Testing

The backend additions are covered by `tests/integration/test_dashboard.py`:
tenant isolation on list/detail/reconciliation-run, status filtering and
pagination, ordering, detail payload completeness (events/attempts/refunds/
ledger entries), and summary aggregation against real counts and volume.

The frontend has no automated test suite of its own -- consistent with the
brief's "kept simple and fast to build" framing for this phase, verification
was a full manual pass through the live dashboard against the live API and
a real Postgres database: connect, create a payment, capture it, refund it,
create a second payment via the `timeout` scenario, resolve it through the
Reconciliation page, and confirm the Overview page's aggregate numbers
reflect all of it. `npm run build` (`tsc -b && vite build`) and `oxlint`
both pass clean.

The Phase 21 redesign was verified the same way: every page driven live
against the real API and a real payment (command palette search resolving
to a real payment by ID, Reconciliation's "everything in sync" empty state,
a real captured payment's lifecycle/ledger/Idempotency Inspector all
matching its actual attempt count and balance), plus a dedicated mobile
pass (375px viewport, off-canvas sidebar drawer open/close/navigate) and a
final `npm run build` to confirm the visual rewrite didn't regress the
production bundle.

Run the backend suite: `pytest tests/` (requires `docker compose up -d postgres redis` and
`alembic upgrade head` first). Run the dashboard: `npm install && npm run dev`
inside `frontend/`, against a running API (`VITE_API_BASE_URL`, default
`http://localhost:8000`).
