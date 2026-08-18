// The idempotency-storm scenario docs/architecture.md's technology-choices
// note calls out by name: many virtual users firing the *same*
// Idempotency-Key and request body at once. Every prior concurrency proof
// in this codebase (tests/concurrency/test_payment_api_race.py) used 100
// asyncio-gathered requests inside one Python process; this is the same
// invariant under a real load-generator's connection pool and OS-level
// scheduling instead of a single event loop, which is a meaningfully
// different kind of "concurrent" to have proven it under.
//
// k6 alone can only assert on HTTP-level facts (status codes) -- it has no
// database access. The follow-up check that exactly one payment record and
// one provider authorization resulted from this whole storm is done by
// scripts/run_load_test.py after this run finishes, querying Postgres
// directly, mirroring how the existing asyncio-based concurrency test
// verifies its own outcome.
//
// Usage:
//   k6 run -e BASE_URL=http://localhost:8000 -e API_KEY=sk_test_... \
//     -e IDEMPOTENCY_KEY=<uuid> loadtest/idempotency_storm.js

import http from "k6/http";
import { check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const API_KEY = __ENV.API_KEY;
const IDEMPOTENCY_KEY = __ENV.IDEMPOTENCY_KEY;
const VUS = 50;

if (!API_KEY) {
  throw new Error("Set -e API_KEY=<merchant api key> (see scripts/run_load_test.py)");
}
if (!IDEMPOTENCY_KEY) {
  throw new Error("Set -e IDEMPOTENCY_KEY=<uuid> -- must be unique per run (see scripts/run_load_test.py)");
}

// per-vu-iterations with a fixed VU count (no ramp) starts every VU at
// once, which is what "storm" means here -- shared-iterations would let k6
// spread the 50 iterations out however it likes.
export const options = {
  scenarios: {
    storm: {
      executor: "per-vu-iterations",
      vus: VUS,
      iterations: 1,
      maxDuration: "30s",
    },
  },
};

// Fixed body -- every VU must send byte-identical request content, since
// the API's idempotency claim treats a mismatched fingerprint under the
// same key as a conflict (a different, also-tested scenario), not this one.
const PAYLOAD = JSON.stringify({
  amount: 12345,
  currency: "USD",
  merchant_reference: "loadtest-idempotency-storm",
  payment_method: { type: "token", token: "pm_demo_ok" },
});

export default function () {
  const response = http.post(`${BASE_URL}/v1/payments`, PAYLOAD, {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${API_KEY}`,
      "Idempotency-Key": IDEMPOTENCY_KEY,
    },
  });

  // Every well-formed outcome is 201 (the winner, or a replay of the
  // winner's response) or 409 (a caller that hit IN_PROGRESS during the
  // brief window before the winner completes) -- never a 5xx, and never
  // anything else.
  check(response, {
    "status is 201 or 409": (r) => r.status === 201 || r.status === 409,
  });
}
