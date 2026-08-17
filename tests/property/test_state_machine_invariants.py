"""Property-based checks that the transition table itself can never regress
into something unsafe, regardless of which specific transitions get added or
removed in future phases (e.g. Phase 8 refund wiring)."""

from domain.state_machine import (
    TERMINAL_PAYMENT_STATUSES,
    Actor,
    PaymentStatus,
    allowed_payment_transitions,
    is_valid_payment_transition,
)
from hypothesis import given
from hypothesis import strategies as st

payment_statuses = st.sampled_from(list(PaymentStatus))
actors = st.one_of(st.none(), st.sampled_from(list(Actor)))


@given(status=payment_statuses)
def test_terminal_statuses_never_have_outgoing_transitions(status):
    if status in TERMINAL_PAYMENT_STATUSES:
        assert allowed_payment_transitions(status) == frozenset()


@given(from_status=payment_statuses, actor=actors)
def test_failed_can_never_transition_to_succeeded(from_status, actor):
    """FAILED -> SUCCEEDED must never be reachable through any actor, from any
    starting status other than via UNKNOWN + reconciliation (a distinct,
    explicitly-modeled path -- see ADR-008). This directly encodes the
    invariant from docs/architecture.md section 6."""
    if from_status is PaymentStatus.FAILED:
        assert not is_valid_payment_transition(from_status, PaymentStatus.SUCCEEDED, actor)


@given(actor=st.one_of(st.none(), st.sampled_from([Actor.API, Actor.WORKER, Actor.WEBHOOK])))
def test_unknown_only_resolves_via_reconciliation(actor):
    """A payment stuck in UNKNOWN must never be resolved by the API, worker,
    or webhook path directly -- only reconciliation may resolve it (ADR-008).
    Resolving it any other way risks a blind retry double-charging a
    customer whose original request may already have succeeded (ADR-005)."""
    assert not is_valid_payment_transition(PaymentStatus.UNKNOWN, PaymentStatus.SUCCEEDED, actor)
    assert not is_valid_payment_transition(PaymentStatus.UNKNOWN, PaymentStatus.FAILED, actor)


@given(from_status=payment_statuses, to_status=payment_statuses)
def test_self_transitions_are_forbidden_except_reconciliation_unknown_retry(from_status, to_status):
    if from_status is not to_status:
        return
    if from_status is PaymentStatus.UNKNOWN:
        assert is_valid_payment_transition(from_status, to_status, Actor.RECONCILIATION)
    else:
        assert not is_valid_payment_transition(from_status, to_status, None)
