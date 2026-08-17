# ADR-004: Provider Abstraction

## Status
Accepted

## Problem
PayGuard must support multiple payment providers without every part of the system
(state machine, retry classification, reconciliation) needing to know each provider's
specific response formats, status vocabularies, and quirks. It also must be fully
runnable and testable locally with zero real financial transactions or credentials.

## Options considered

1. **Call each provider's SDK directly from business logic, branch on provider type
   where needed.** Fast to write initially, but couples payment/refund/reconciliation
   logic to N provider-specific vocabularies, and makes deterministic local testing of
   failure modes (timeouts, unknown outcomes) dependent on either mocking each SDK
   separately or hitting real sandboxes. Rejected.
2. **A single `PaymentProvider` protocol with `authorize/capture/refund/
   get_payment_status`, returning a closed result vocabulary (`SUCCEEDED | DECLINED |
   TEMPORARY_FAILURE | UNKNOWN`), implemented by a `MockProvider` plus
   provider-specific adapters that translate their native responses into that closed
   vocabulary.** Chosen.

## Decision
Every provider integration implements the same `PaymentProvider` protocol
(`packages/providers/`). The rest of the codebase (state machine, retry engine,
reconciliation) only ever reasons about the protocol's closed result type, never a raw
provider status string — translation from provider-native responses into
`SUCCEEDED/DECLINED/TEMPORARY_FAILURE/UNKNOWN` happens once, inside the adapter, and is
the adapter's primary responsibility and primary source of bugs to test carefully.

`get_payment_status` is a required method, not optional, because it is the mechanism
reconciliation uses to resolve an `UNKNOWN` outcome — a provider adapter that cannot
answer "what actually happened to transaction X" cannot fully participate in this
system's safety guarantees, and that requirement is enforced at the interface level.

`MockProvider` is the only provider implemented in early phases. It accepts a scenario
hint (per-request or via global/merchant chaos configuration) to deterministically
return `SUCCESS, DECLINED, TIMEOUT, TEMPORARY_FAILURE, DUPLICATE_RESPONSE,
UNKNOWN_RESULT, SLOW_RESPONSE`, and drives its own asynchronous webhook delivery
(including on-demand duplicate/out-of-order delivery), so every failure-mode test and
demo scenario in this project is reproducible without network flakiness standing in
for deliberate test scenarios.

## Tradeoffs
- The closed result vocabulary is necessarily a lossy simplification of what real PSPs
  return (e.g. detailed decline reason codes). Adapters are expected to preserve the
  raw provider response in `provider_transactions.raw_response` for audit/debugging
  even though business logic only branches on the simplified vocabulary — nothing is
  actually thrown away, it's just not load-bearing for control flow.
- Adding a second real provider adapter later requires writing and testing its
  translation layer in isolation before wiring it into the rest of the system; the
  interface is designed so that work is additive, not a refactor of existing logic.

## Failure modes
- **A provider's SDK throws an unrecognized/unmapped error**: the adapter is
  required to default to `UNKNOWN` rather than guessing `SUCCEEDED` or `FAILED` — an
  unmapped error is, by definition, an outcome the system doesn't understand yet, and
  `UNKNOWN` routes it into reconciliation instead of a possibly-wrong automatic
  resolution.
- **`get_payment_status` itself times out or errors during reconciliation**: treated as
  `STILL_UNKNOWN`, logged, and retried on the next reconciliation pass rather than
  escalated to a guessed resolution.
