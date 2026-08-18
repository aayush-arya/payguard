"""Structured JSON logging with correlation IDs (product brief section 23).

Correlation IDs (request_id, merchant_id, payment_id, provider_transaction_id)
are threaded through `contextvars`, not passed as an argument to every
function that might want to log something. Once `bind_context()` sets them
for the current async task, every log line emitted anywhere in that task's
call graph automatically carries them -- a payment created deep inside
packages/payments/service.py and a webhook applied later in
packages/webhooks/service.py both end up correlatable by payment_id without
either module needing to know about logging IDs explicitly.

No raw payment tokens, API keys, or webhook secrets are ever logged --
nothing in this codebase passes them to a logger, by construction, not by a
redaction filter bolted on afterward (docs/observability.md).
"""

from __future__ import annotations

import contextlib
import json
import logging
from contextvars import ContextVar
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
merchant_id_var: ContextVar[str | None] = ContextVar("merchant_id", default=None)
payment_id_var: ContextVar[str | None] = ContextVar("payment_id", default=None)
provider_transaction_id_var: ContextVar[str | None] = ContextVar("provider_transaction_id", default=None)

_CONTEXT_VARS: dict[str, ContextVar[str | None]] = {
    "request_id": request_id_var,
    "merchant_id": merchant_id_var,
    "payment_id": payment_id_var,
    "provider_transaction_id": provider_transaction_id_var,
}


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name, var in _CONTEXT_VARS.items():
            value = var.get()
            if value is not None:
                payload[name] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


@contextlib.contextmanager
def bind_context(**kwargs: str | None):
    """Set one or more correlation IDs for the duration of the `with` block,
    restoring whatever was there before on exit -- safe to nest (e.g. an
    outer request-scoped request_id plus an inner payment_id bound once the
    payment exists)."""
    unknown = set(kwargs) - set(_CONTEXT_VARS)
    if unknown:
        raise ValueError(f"Unknown context var(s): {sorted(unknown)}")
    tokens = {name: _CONTEXT_VARS[name].set(value) for name, value in kwargs.items()}
    try:
        yield
    finally:
        for name, token in tokens.items():
            _CONTEXT_VARS[name].reset(token)
