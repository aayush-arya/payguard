"""Consistent error envelope (docs/architecture.md section 17):

    {"error": {"code": "...", "message": "...", "request_id": "..."}}

This is the only place that maps a domain-level PayGuardError.code to an HTTP
status -- packages/payments and packages/idempotency never think in terms of
status codes, only error codes.
"""

from __future__ import annotations

from domain.errors import PayGuardError
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

_STATUS_BY_CODE: dict[str, int] = {
    "INVALID_REQUEST": status.HTTP_400_BAD_REQUEST,
    "INVALID_CURRENCY": status.HTTP_400_BAD_REQUEST,
    "INVALID_AMOUNT": status.HTTP_400_BAD_REQUEST,
    "IDEMPOTENCY_KEY_REQUIRED": status.HTTP_400_BAD_REQUEST,
    "IDEMPOTENCY_KEY_REUSED": status.HTTP_409_CONFLICT,
    "REQUEST_IN_PROGRESS": status.HTTP_409_CONFLICT,
    "PAYMENT_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "INVALID_STATE_TRANSITION": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "PAYMENT_DECLINED": status.HTTP_402_PAYMENT_REQUIRED,
    "PROVIDER_TIMEOUT": status.HTTP_504_GATEWAY_TIMEOUT,
    "PROVIDER_UNAVAILABLE": status.HTTP_503_SERVICE_UNAVAILABLE,
    "REFUND_EXCEEDS_PAYMENT": status.HTTP_409_CONFLICT,
    "WEBHOOK_SIGNATURE_INVALID": status.HTTP_401_UNAUTHORIZED,
    "RATE_LIMITED": status.HTTP_429_TOO_MANY_REQUESTS,
    "UNAUTHORIZED": status.HTTP_401_UNAUTHORIZED,
}


def _error_response(request: Request, code: str, message: str, status_code: int) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(PayGuardError)
    async def _payguard_error_handler(request: Request, exc: PayGuardError) -> JSONResponse:
        status_code = _STATUS_BY_CODE.get(exc.code, status.HTTP_400_BAD_REQUEST)
        return _error_response(request, exc.code, exc.message, status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        message = first.get("msg", "The request body failed validation.")
        return _error_response(request, "INVALID_REQUEST", message, status.HTTP_400_BAD_REQUEST)
