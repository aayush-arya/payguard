import pytest
from domain.state_machine import (
    Actor,
    InvalidStateTransition,
    PaymentStatus,
    RefundStatus,
    allowed_payment_transitions,
    allowed_refund_transitions,
    is_valid_payment_transition,
    is_valid_refund_transition,
    validate_payment_transition,
    validate_refund_transition,
)

ALLOWED_PAYMENT_TRANSITIONS = [
    (PaymentStatus.CREATED, PaymentStatus.PROCESSING, None),
    (PaymentStatus.PROCESSING, PaymentStatus.SUCCEEDED, None),
    (PaymentStatus.PROCESSING, PaymentStatus.FAILED, None),
    (PaymentStatus.PROCESSING, PaymentStatus.REQUIRES_ACTION, None),
    (PaymentStatus.PROCESSING, PaymentStatus.UNKNOWN, None),
    (PaymentStatus.REQUIRES_ACTION, PaymentStatus.PROCESSING, None),
    (PaymentStatus.REQUIRES_ACTION, PaymentStatus.FAILED, None),
    (PaymentStatus.UNKNOWN, PaymentStatus.SUCCEEDED, Actor.RECONCILIATION),
    (PaymentStatus.UNKNOWN, PaymentStatus.FAILED, Actor.RECONCILIATION),
    (PaymentStatus.UNKNOWN, PaymentStatus.UNKNOWN, Actor.RECONCILIATION),
    (PaymentStatus.SUCCEEDED, PaymentStatus.REFUND_PENDING, None),
    (PaymentStatus.REFUND_PENDING, PaymentStatus.REFUNDED, None),
    (PaymentStatus.REFUND_PENDING, PaymentStatus.REFUND_FAILED, None),
    (PaymentStatus.REFUND_FAILED, PaymentStatus.REFUND_PENDING, None),
]


@pytest.mark.parametrize("from_status,to_status,actor", ALLOWED_PAYMENT_TRANSITIONS)
def test_allowed_payment_transitions_are_valid(from_status, to_status, actor):
    assert is_valid_payment_transition(from_status, to_status, actor)
    validate_payment_transition(from_status, to_status, actor)  # must not raise


FORBIDDEN_PAYMENT_TRANSITIONS = [
    (PaymentStatus.FAILED, PaymentStatus.SUCCEEDED, None),
    (PaymentStatus.FAILED, PaymentStatus.SUCCEEDED, Actor.RECONCILIATION),
    (PaymentStatus.SUCCEEDED, PaymentStatus.CREATED, None),
    (PaymentStatus.CREATED, PaymentStatus.SUCCEEDED, None),  # cannot skip PROCESSING
    (PaymentStatus.REFUNDED, PaymentStatus.SUCCEEDED, None),  # terminal
    (PaymentStatus.REFUNDED, PaymentStatus.REFUND_PENDING, None),  # terminal
    (PaymentStatus.CREATED, PaymentStatus.FAILED, None),
    (PaymentStatus.PROCESSING, PaymentStatus.CREATED, None),
    # UNKNOWN can only be resolved by reconciliation, not API/worker/webhook directly.
    (PaymentStatus.UNKNOWN, PaymentStatus.SUCCEEDED, None),
    (PaymentStatus.UNKNOWN, PaymentStatus.SUCCEEDED, Actor.API),
    (PaymentStatus.UNKNOWN, PaymentStatus.SUCCEEDED, Actor.WORKER),
    (PaymentStatus.UNKNOWN, PaymentStatus.FAILED, Actor.WEBHOOK),
]


@pytest.mark.parametrize("from_status,to_status,actor", FORBIDDEN_PAYMENT_TRANSITIONS)
def test_forbidden_payment_transitions_are_invalid(from_status, to_status, actor):
    assert not is_valid_payment_transition(from_status, to_status, actor)
    with pytest.raises(InvalidStateTransition):
        validate_payment_transition(from_status, to_status, actor)


def test_terminal_payment_statuses_have_no_outgoing_transitions():
    assert allowed_payment_transitions(PaymentStatus.FAILED) == frozenset()
    assert allowed_payment_transitions(PaymentStatus.REFUNDED) == frozenset()


def test_every_payment_status_is_reachable_or_initial():
    reachable = {PaymentStatus.CREATED}
    for targets in [allowed_payment_transitions(s) for s in PaymentStatus]:
        reachable |= targets
    assert reachable == set(PaymentStatus)


ALLOWED_REFUND_TRANSITIONS = [
    (RefundStatus.PENDING, RefundStatus.SUCCEEDED),
    (RefundStatus.PENDING, RefundStatus.FAILED),
    (RefundStatus.FAILED, RefundStatus.PENDING),
]


@pytest.mark.parametrize("from_status,to_status", ALLOWED_REFUND_TRANSITIONS)
def test_allowed_refund_transitions_are_valid(from_status, to_status):
    assert is_valid_refund_transition(from_status, to_status)
    validate_refund_transition(from_status, to_status)


FORBIDDEN_REFUND_TRANSITIONS = [
    (RefundStatus.SUCCEEDED, RefundStatus.FAILED),
    (RefundStatus.SUCCEEDED, RefundStatus.PENDING),
    (RefundStatus.PENDING, RefundStatus.PENDING),
]


@pytest.mark.parametrize("from_status,to_status", FORBIDDEN_REFUND_TRANSITIONS)
def test_forbidden_refund_transitions_are_invalid(from_status, to_status):
    assert not is_valid_refund_transition(from_status, to_status)
    with pytest.raises(InvalidStateTransition):
        validate_refund_transition(from_status, to_status)


def test_refund_succeeded_is_terminal():
    assert allowed_refund_transitions(RefundStatus.SUCCEEDED) == frozenset()


def test_invalid_state_transition_message_includes_actor():
    exc = InvalidStateTransition(PaymentStatus.UNKNOWN, PaymentStatus.SUCCEEDED, Actor.API)
    assert "UNKNOWN" in str(exc)
    assert "SUCCEEDED" in str(exc)
    assert "API" in str(exc)
