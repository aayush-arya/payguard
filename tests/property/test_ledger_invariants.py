"""Property-based checks on the ledger entry-pair builders (ADR-007): every
pair this module can ever produce must have equal debit and credit amounts,
share one ledger_transaction_id, and reference the payment they're about --
for any amount, not just the examples exercised by the integration tests.
"""

import uuid

from hypothesis import given
from hypothesis import strategies as st
from ledger.service import build_payment_settled_pair, build_refund_settled_pair

positive_amounts = st.integers(min_value=1, max_value=10_000_000_00)
payment_ids = st.uuids()


@given(payment_intent_id=payment_ids, amount_minor=positive_amounts)
def test_payment_settled_pair_always_balances(payment_intent_id: uuid.UUID, amount_minor: int):
    debit, credit = build_payment_settled_pair(payment_intent_id=payment_intent_id, amount_minor=amount_minor)
    assert debit.direction == "DEBIT"
    assert credit.direction == "CREDIT"
    assert debit.amount_minor == credit.amount_minor == amount_minor
    assert debit.ledger_transaction_id == credit.ledger_transaction_id
    assert debit.payment_intent_id == credit.payment_intent_id == payment_intent_id
    assert debit.account != credit.account


@given(payment_intent_id=payment_ids, amount_minor=positive_amounts)
def test_refund_settled_pair_always_balances(payment_intent_id: uuid.UUID, amount_minor: int):
    debit, credit = build_refund_settled_pair(payment_intent_id=payment_intent_id, amount_minor=amount_minor)
    assert debit.direction == "DEBIT"
    assert credit.direction == "CREDIT"
    assert debit.amount_minor == credit.amount_minor == amount_minor
    assert debit.ledger_transaction_id == credit.ledger_transaction_id
    assert debit.payment_intent_id == credit.payment_intent_id == payment_intent_id
    assert debit.account != credit.account


@given(payment_intent_id=payment_ids, amount_minor=positive_amounts)
def test_payment_and_refund_pairs_never_share_a_ledger_transaction_id(
    payment_intent_id: uuid.UUID, amount_minor: int
):
    payment_debit, _ = build_payment_settled_pair(
        payment_intent_id=payment_intent_id, amount_minor=amount_minor
    )
    refund_debit, _ = build_refund_settled_pair(
        payment_intent_id=payment_intent_id, amount_minor=amount_minor
    )
    assert payment_debit.ledger_transaction_id != refund_debit.ledger_transaction_id


@given(payment_intent_id=payment_ids, amount_minor=positive_amounts)
def test_each_call_mints_a_fresh_ledger_transaction_id(payment_intent_id: uuid.UUID, amount_minor: int):
    """Two settlements of the same payment for the same amount must still be
    distinguishable transactions -- e.g. two separate partial refunds that
    happen to be for identical amounts."""
    first_debit, _ = build_refund_settled_pair(payment_intent_id=payment_intent_id, amount_minor=amount_minor)
    second_debit, _ = build_refund_settled_pair(
        payment_intent_id=payment_intent_id, amount_minor=amount_minor
    )
    assert first_debit.ledger_transaction_id != second_debit.ledger_transaction_id
