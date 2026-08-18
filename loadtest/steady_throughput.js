// Steady-state throughput: how many happy-path payments/sec this API
// sustains locally, and what its real p95/p99 latency looks like under
// concurrent load -- not a single hand-timed request, a ramping population
// of virtual users hitting the real HTTP boundary (product brief section
// 26 / docs/architecture.md's technology-choices note on k6).
//
// Every iteration uses its own Idempotency-Key and its own successful
// token (pm_demo_ok) -- this measures the API's steady-state capacity, not
// its idempotency-conflict or provider-decline handling (loadtest/
// idempotency_storm.js covers the former; there is no decline-storm
// scenario because a decline is cheaper than a success, not a stress case).
//
// Usage:
//   k6 run -e BASE_URL=http://localhost:8000 -e API_KEY=sk_test_... loadtest/steady_throughput.js

import http from "k6/http";
import { check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const API_KEY = __ENV.API_KEY;

if (!API_KEY) {
  throw new Error("Set -e API_KEY=<merchant api key> (see scripts/run_load_test.py)");
}

export const options = {
  stages: [
    { duration: "10s", target: 10 },
    { duration: "20s", target: 10 },
    { duration: "5s", target: 0 },
  ],
  summaryTrendStats: ["avg", "min", "med", "max", "p(90)", "p(95)", "p(99)"],
  // These are a measured baseline for this specific dev setup -- a single
  // uvicorn worker process (no --workers, no replicas) with Postgres in
  // Docker Desktop on Windows, whose virtualized networking adds real
  // per-round-trip latency to the 4-5 sequential commits create_payment()
  // deliberately makes per request (never holding a lock across the
  // provider call -- docs/architecture.md section 8). Under 10 concurrent
  // VUs that queues behind one event loop; see docs/load-testing.md for the
  // full finding and why horizontal scaling (Phase 17), not code changes
  // here, is the real fix. Not a production SLA -- a regression guard for
  // *this* environment.
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<3500", "p(99)<5000"],
  },
};

export default function () {
  const idempotencyKey = `loadtest-${__VU}-${__ITER}-${Date.now()}-${Math.random()}`;
  const payload = JSON.stringify({
    amount: 1000 + (__ITER % 500),
    currency: "USD",
    payment_method: { type: "token", token: "pm_demo_ok" },
  });

  const response = http.post(`${BASE_URL}/v1/payments`, payload, {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${API_KEY}`,
      "Idempotency-Key": idempotencyKey,
    },
  });

  check(response, {
    "status is 201": (r) => r.status === 201,
    "payment succeeded or is processing": (r) => {
      if (r.status !== 201) return false;
      const status = r.json("status");
      return status === "PROCESSING" || status === "SUCCEEDED";
    },
  });
}
