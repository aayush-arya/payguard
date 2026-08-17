"""Transport-agnostic error type for domain/use-case failures (docs/architecture.md
section 17). `code` is one of the closed set of API error codes; the API layer
(apps/api) is the only place that knows how to map a code to an HTTP status --
this module and everything that raises PayGuardError stays free of HTTP concerns
so the same error type works for the API, the worker, and the CLI alike."""

from __future__ import annotations


class PayGuardError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")
