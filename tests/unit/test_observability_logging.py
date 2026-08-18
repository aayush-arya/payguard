"""Unit tests for structured JSON logging and correlation-ID context binding
(product brief section 23) -- no database needed, these are pure formatting
and contextvars behavior."""

import io
import json
import logging

import pytest
from observability.logging import JSONFormatter, bind_context, request_id_var


def _capture_json_log(logger_name: str, log_fn) -> dict:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    logger = logging.getLogger(logger_name)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        log_fn(logger)
    finally:
        logger.removeHandler(handler)
    return json.loads(stream.getvalue().strip())


def test_log_record_is_valid_json_with_core_fields():
    payload = _capture_json_log("test.basic", lambda log: log.info("hello world"))
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert "timestamp" in payload
    assert "logger" in payload


def test_log_without_bound_context_omits_correlation_fields():
    payload = _capture_json_log("test.no_context", lambda log: log.info("no context"))
    assert "request_id" not in payload
    assert "merchant_id" not in payload
    assert "payment_id" not in payload


def test_bind_context_adds_correlation_ids_to_log_output():
    def do_log(log):
        with bind_context(request_id="req_abc", merchant_id="merch_123"):
            log.info("inside context")

    payload = _capture_json_log("test.context", do_log)
    assert payload["request_id"] == "req_abc"
    assert payload["merchant_id"] == "merch_123"


def test_context_does_not_leak_into_logs_emitted_after_the_block_exits():
    def do_log(log):
        with bind_context(payment_id="pay_1"):
            pass
        log.info("outside the context block")

    payload = _capture_json_log("test.leak", do_log)
    assert "payment_id" not in payload


def test_bind_context_nesting_restores_the_outer_value_on_exit():
    with bind_context(request_id="outer"):
        assert request_id_var.get() == "outer"
        with bind_context(request_id="inner"):
            assert request_id_var.get() == "inner"
        assert request_id_var.get() == "outer"
    assert request_id_var.get() is None


def test_bind_context_rejects_an_unknown_field_name():
    with pytest.raises(ValueError):
        with bind_context(not_a_real_field="x"):
            pass
