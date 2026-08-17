from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, StrEnum


class PaymentStatus(StrEnum):
    CREATED = "CREATED"
    PROCESSING = "PROCESSING"
    REQUIRES_ACTION = "REQUIRES_ACTION"
    UNKNOWN = "UNKNOWN"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"
    REFUND_FAILED = "REFUND_FAILED"


TERMINAL_PAYMENT_STATUSES = frozenset({PaymentStatus.FAILED, PaymentStatus.REFUNDED})


class RefundStatus(StrEnum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


TERMINAL_REFUND_STATUSES = frozenset({RefundStatus.SUCCEEDED})


class Actor(StrEnum):
    API = "API"
    WORKER = "WORKER"
    WEBHOOK = "WEBHOOK"
    RECONCILIATION = "RECONCILIATION"


class InvalidStateTransition(Exception):
    def __init__(self, from_status: Enum, to_status: Enum, actor: Actor | None = None) -> None:
        self.from_status = from_status
        self.to_status = to_status
        self.actor = actor
        actor_note = f" by actor {actor.value}" if actor is not None else ""
        super().__init__(f"Invalid transition: {from_status.value} -> {to_status.value}{actor_note}")


@dataclass(frozen=True)
class _Transition:
    to_status: PaymentStatus
    # None means any actor may perform this transition.
    allowed_actors: frozenset[Actor] | None = None


# UNKNOWN can only be resolved by reconciliation (ADR-008) -- never by a blind
# retry from the API or worker path, since that is exactly the scenario that
# could double-charge a customer (ADR-005).
_PAYMENT_TRANSITIONS: dict[PaymentStatus, tuple[_Transition, ...]] = {
    PaymentStatus.CREATED: (_Transition(PaymentStatus.PROCESSING),),
    PaymentStatus.PROCESSING: (
        _Transition(PaymentStatus.SUCCEEDED),
        _Transition(PaymentStatus.FAILED),
        _Transition(PaymentStatus.REQUIRES_ACTION),
        _Transition(PaymentStatus.UNKNOWN),
    ),
    PaymentStatus.REQUIRES_ACTION: (
        _Transition(PaymentStatus.PROCESSING),
        _Transition(PaymentStatus.FAILED),
    ),
    PaymentStatus.UNKNOWN: (
        _Transition(PaymentStatus.SUCCEEDED, frozenset({Actor.RECONCILIATION})),
        _Transition(PaymentStatus.FAILED, frozenset({Actor.RECONCILIATION})),
        _Transition(PaymentStatus.UNKNOWN, frozenset({Actor.RECONCILIATION})),
    ),
    PaymentStatus.SUCCEEDED: (_Transition(PaymentStatus.REFUND_PENDING),),
    PaymentStatus.REFUND_PENDING: (
        # Fully refunded (sum of successful refunds == payment amount): terminal.
        _Transition(PaymentStatus.REFUNDED),
        # This refund attempt failed at the provider: retryable via
        # REFUND_FAILED -> REFUND_PENDING below.
        _Transition(PaymentStatus.REFUND_FAILED),
        # A *partial* refund succeeded but did not exhaust the payment
        # amount -- the payment is still fundamentally successful, just with
        # some money returned. How much has been refunded is a derived fact
        # from summing the refunds table (docs/refunds.md), not something
        # that needs its own top-level status; SUCCEEDED is reused rather
        # than adding a PARTIALLY_REFUNDED status (Phase 8 addition to the
        # Phase 1 transition table -- multi-partial-refund flows genuinely
        # need this leg, which wasn't exercised by anything before refunds
        # existed).
        _Transition(PaymentStatus.SUCCEEDED),
    ),
    PaymentStatus.REFUND_FAILED: (_Transition(PaymentStatus.REFUND_PENDING),),
    PaymentStatus.FAILED: (),
    PaymentStatus.REFUNDED: (),
}

_REFUND_TRANSITIONS: dict[RefundStatus, tuple[RefundStatus, ...]] = {
    RefundStatus.PENDING: (RefundStatus.SUCCEEDED, RefundStatus.FAILED),
    RefundStatus.FAILED: (RefundStatus.PENDING,),
    RefundStatus.SUCCEEDED: (),
}


def is_valid_payment_transition(
    from_status: PaymentStatus, to_status: PaymentStatus, actor: Actor | None = None
) -> bool:
    for transition in _PAYMENT_TRANSITIONS.get(from_status, ()):
        if transition.to_status != to_status:
            continue
        if transition.allowed_actors is None:
            return True
        return actor in transition.allowed_actors
    return False


def validate_payment_transition(
    from_status: PaymentStatus, to_status: PaymentStatus, actor: Actor | None = None
) -> None:
    if not is_valid_payment_transition(from_status, to_status, actor):
        raise InvalidStateTransition(from_status, to_status, actor)


def allowed_payment_transitions(from_status: PaymentStatus) -> frozenset[PaymentStatus]:
    return frozenset(t.to_status for t in _PAYMENT_TRANSITIONS.get(from_status, ()))


def is_valid_refund_transition(from_status: RefundStatus, to_status: RefundStatus) -> bool:
    return to_status in _REFUND_TRANSITIONS.get(from_status, ())


def validate_refund_transition(from_status: RefundStatus, to_status: RefundStatus) -> None:
    if not is_valid_refund_transition(from_status, to_status):
        raise InvalidStateTransition(from_status, to_status)


def allowed_refund_transitions(from_status: RefundStatus) -> frozenset[RefundStatus]:
    return frozenset(_REFUND_TRANSITIONS.get(from_status, ()))
