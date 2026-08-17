"""SQLAlchemy models for the PayGuard schema.

Schema mirrors docs/architecture.md section 7 (ERD). Status columns are plain
text with CHECK constraints rather than native Postgres ENUM types, so adding a
new status later is a plain migration instead of an ALTER TYPE. The
domain.state_machine module is the single source of truth for which status
values and transitions are valid -- the CHECK constraints here are a database-
level backstop against a bug that bypasses the state machine, not the primary
mechanism.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String, nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_at: Mapped[datetime] = _created_at()

    customers: Mapped[list[Customer]] = relationship(back_populates="merchant")
    payment_intents: Mapped[list[PaymentIntent]] = relationship(back_populates="merchant")

    __table_args__ = (CheckConstraint("status IN ('active', 'suspended')", name="ck_merchants_status"),)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = _uuid_pk()
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False
    )
    external_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = _created_at()

    merchant: Mapped[Merchant] = relationship(back_populates="customers")
    payment_methods: Mapped[list[PaymentMethod]] = relationship(back_populates="customer")

    __table_args__ = (
        UniqueConstraint("merchant_id", "external_reference", name="uq_customers_merchant_external_ref"),
        Index("ix_customers_merchant_id", "merchant_id"),
    )


class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id: Mapped[uuid.UUID] = _uuid_pk()
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False
    )
    # Tokenized/mock reference only. PayGuard never stores real card numbers,
    # CVVs, or bank credentials -- see docs/architecture.md section 13.
    type: Mapped[str] = mapped_column(String, nullable=False)
    provider_token: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = _created_at()

    customer: Mapped[Customer] = relationship(back_populates="payment_methods")

    __table_args__ = (
        CheckConstraint("type IN ('token')", name="ck_payment_methods_type"),
        Index("ix_payment_methods_customer_id", "customer_id"),
    )


_PAYMENT_STATUSES = (
    "CREATED",
    "PROCESSING",
    "REQUIRES_ACTION",
    "UNKNOWN",
    "SUCCEEDED",
    "FAILED",
    "REFUND_PENDING",
    "REFUNDED",
    "REFUND_FAILED",
)


class PaymentIntent(Base):
    __tablename__ = "payment_intents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="CREATED")
    merchant_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    # Belt-and-suspenders assertion (see docs/adr/ADR-002): every UPDATE that
    # runs while holding the row's FOR UPDATE lock also bumps this. A write
    # that unexpectedly affects zero rows on a version match is a locking bug.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    merchant: Mapped[Merchant] = relationship(back_populates="payment_intents")
    attempts: Mapped[list[PaymentAttempt]] = relationship(back_populates="payment_intent")
    events: Mapped[list[PaymentEvent]] = relationship(back_populates="payment_intent")
    refunds: Mapped[list[Refund]] = relationship(back_populates="payment_intent")

    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_payment_intents_amount_positive"),
        CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name="ck_payment_intents_currency_iso4217",
        ),
        CheckConstraint(
            f"status IN {_PAYMENT_STATUSES!r}",
            name="ck_payment_intents_status",
        ),
        Index("ix_payment_intents_merchant_status", "merchant_id", "status"),
        Index("ix_payment_intents_merchant_created", "merchant_id", "created_at"),
        Index("ix_payment_intents_merchant_reference", "merchant_id", "merchant_reference"),
    )


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    payment_intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payment_intents.id"), nullable=False
    )
    provider_name: Mapped[str] = mapped_column(String, nullable=False)
    # Mirrors providers.PaymentProvider's closed result vocabulary (ADR-004).
    status: Mapped[str] = mapped_column(String, nullable=False)
    # PERMANENT | TRANSIENT | UNKNOWN, per ADR-005. Null until classified.
    failure_classification: Mapped[str | None] = mapped_column(String, nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = _created_at()

    payment_intent: Mapped[PaymentIntent] = relationship(back_populates="attempts")
    provider_transaction: Mapped[ProviderTransaction | None] = relationship(
        back_populates="payment_attempt", uselist=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('SUCCEEDED', 'DECLINED', 'TEMPORARY_FAILURE', 'UNKNOWN')",
            name="ck_payment_attempts_status",
        ),
        CheckConstraint(
            "failure_classification IS NULL "
            "OR failure_classification IN ('PERMANENT', 'TRANSIENT', 'UNKNOWN')",
            name="ck_payment_attempts_failure_classification",
        ),
        UniqueConstraint("payment_intent_id", "attempt_number", name="uq_payment_attempts_intent_attempt_no"),
    )


class ProviderTransaction(Base):
    __tablename__ = "provider_transactions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    payment_attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payment_attempts.id"), nullable=False, unique=True
    )
    provider_name: Mapped[str] = mapped_column(String, nullable=False)
    provider_transaction_id: Mapped[str] = mapped_column(String, nullable=False)
    raw_status: Mapped[str] = mapped_column(String, nullable=False)
    raw_response: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created_at()

    payment_attempt: Mapped[PaymentAttempt] = relationship(back_populates="provider_transaction")

    __table_args__ = (
        UniqueConstraint(
            "provider_name", "provider_transaction_id", name="uq_provider_transactions_provider_txn"
        ),
    )


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    id: Mapped[uuid.UUID] = _uuid_pk()
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    payment_intent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payment_intents.id"), nullable=True
    )
    # Reserved for refund idempotency (Phase 8) so refunds can reuse this same
    # claim protocol instead of a parallel table -- see docs/architecture.md
    # section 7 (payment_intents/refunds both point at idempotency_keys).
    refund_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("refunds.id"), nullable=True
    )
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # The safety mechanism for idempotency (ADR-001): this is what INSERT
        # ... ON CONFLICT DO NOTHING races against, not application code.
        UniqueConstraint("merchant_id", "idempotency_key", name="uq_idempotency_keys_merchant_key"),
        CheckConstraint("status IN ('PENDING', 'COMPLETED', 'FAILED')", name="ck_idempotency_keys_status"),
    )


class PaymentEvent(Base):
    """Append-only audit trail of every attempted state transition."""

    __tablename__ = "payment_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    payment_intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payment_intents.id"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String, nullable=True)
    to_status: Mapped[str] = mapped_column(String, nullable=False)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    event_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = _created_at()

    payment_intent: Mapped[PaymentIntent] = relationship(back_populates="events")

    __table_args__ = (
        CheckConstraint(
            "actor IN ('API', 'WORKER', 'WEBHOOK', 'RECONCILIATION')",
            name="ck_payment_events_actor",
        ),
        Index("ix_payment_events_intent_created", "payment_intent_id", "created_at"),
    )


class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[uuid.UUID] = _uuid_pk()
    payment_intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payment_intents.id"), nullable=False
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    created_at: Mapped[datetime] = _created_at()

    payment_intent: Mapped[PaymentIntent] = relationship(back_populates="refunds")

    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_refunds_amount_positive"),
        CheckConstraint("status IN ('PENDING', 'SUCCEEDED', 'FAILED')", name="ck_refunds_status"),
        Index("ix_refunds_payment_intent_id", "payment_intent_id"),
        # NOTE: "sum(refunds) <= payment amount" is NOT a per-row CHECK
        # constraint -- Postgres CHECK constraints cannot see other rows. The
        # invariant is enforced transactionally: SELECT ... FOR UPDATE the
        # payment row, compute remaining balance, and only then insert a new
        # refund row in the same transaction. See ADR-002 and
        # docs/architecture.md section 15 (Phase 8 implements the write path).
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    aggregate_type: Mapped[str] = mapped_column(String, nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    failure_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'PROCESSED', 'DEAD_LETTER')",
            name="ck_outbox_events_status",
        ),
        # Supports the worker's SELECT ... FOR UPDATE SKIP LOCKED poll query
        # (ADR-003): find PENDING rows whose backoff window has elapsed.
        Index("ix_outbox_events_status_available_at", "status", "available_at"),
    )


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    provider_name: Mapped[str] = mapped_column(String, nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    signature: Mapped[str] = mapped_column(String, nullable=False)
    processing_status: Mapped[str] = mapped_column(String, nullable=False, default="RECEIVED")
    received_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        # The dedup gate for webhook delivery (ADR-006): a provider resending
        # the same event 20 times inserts once, conflicts 19 times.
        UniqueConstraint("provider_name", "provider_event_id", name="uq_webhook_events_provider_event"),
        CheckConstraint(
            "processing_status IN ('RECEIVED', 'PROCESSED', 'IGNORED')",
            name="ck_webhook_events_processing_status",
        ),
    )


class LedgerEntry(Base):
    """Append-only double-entry ledger row. Never updated or deleted (ADR-007)."""

    __tablename__ = "ledger_entries"

    id: Mapped[uuid.UUID] = _uuid_pk()
    payment_intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payment_intents.id"), nullable=False
    )
    # Groups the debit/credit pair (or larger set) that must balance together.
    ledger_transaction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    account: Mapped[str] = mapped_column(String, nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_ledger_entries_amount_positive"),
        CheckConstraint("direction IN ('DEBIT', 'CREDIT')", name="ck_ledger_entries_direction"),
        Index("ix_ledger_entries_transaction_id", "ledger_transaction_id"),
        Index("ix_ledger_entries_payment_intent_id", "payment_intent_id"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=True
    )
    actor: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    audit_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (Index("ix_audit_logs_merchant_created", "merchant_id", "created_at"),)
