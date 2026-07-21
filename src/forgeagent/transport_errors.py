"""Shared transport plumbing for SDK-backed clients: exception classification plus
the retry loop that every ModelClient.complete() runs.

Each `ModelClient` (Anthropic, OpenAI-compatible, ...) wraps its SDK calls in a
`transport` closure that raises `TransportError` for any SDK exception, classified by
`classify_transport_exception`. The classification is by exception class *name* (via
MRO), not `isinstance`, so this module never needs to import any SDK.

`run_with_retries` is the attempt/backoff loop itself: build_request/_parse_response
are the only genuinely per-vendor pieces of complete(), so every concrete client's
complete() reduces to building a request, calling this, and handing it its own
_parse_response.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .client import AttemptObserver, ProviderAttempt
from .models import AssistantMessage, ClientError

# Map SDK exception class names -> (ClientError.kind, retryable). Matched against the
# exception's MRO class names so it works without importing the SDK at module load.
# The OpenAI and Anthropic SDKs both use these names for their equivalent exceptions.
_KIND_BY_EXC_NAME: dict[str, tuple[str, bool]] = {
    "APITimeoutError": ("timeout", True),
    "APIConnectionError": ("network", True),
    "RateLimitError": ("rate_limit", True),
    "InternalServerError": ("network", True),
    "AuthenticationError": ("auth", False),
    "PermissionDeniedError": ("auth", False),
    "BadRequestError": ("invalid_request", False),
    "UnprocessableEntityError": ("invalid_request", False),
}


class TransportError(Exception):
    """Transport-layer failure already classified into a ClientError kind."""

    def __init__(self, kind: str, retryable: bool, message: str):
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable


def _notify_attempt(observer: AttemptObserver | None, event: ProviderAttempt) -> None:
    if observer is None:
        return
    try:
        observer(event)
    except Exception:  # diagnostic hooks must not alter provider behavior
        pass


def classify_transport_exception(exc: BaseException) -> tuple[str, bool]:
    """Classify an exception into (kind, retryable) by its class MRO names.

    Unknown exceptions are ("unknown", False) — not retried, surfaced as-is.
    """
    for klass in type(exc).__mro__:
        mapped = _KIND_BY_EXC_NAME.get(klass.__name__)
        if mapped:
            return mapped
    return ("unknown", False)


def run_with_retries(
    *,
    transport: Callable[[dict, float], Any],
    request: dict,
    timeout_seconds: float,
    max_attempts: int,
    backoff_base_seconds: float,
    backoff_factor: float,
    sleep: Callable[[float], None],
    parse_response: Callable[[Any], AssistantMessage],
    attempt_observer: AttemptObserver | None = None,
) -> AssistantMessage | ClientError:
    """Call `transport(request, timeout_seconds)`, retrying retryable TransportErrors
    with exponential backoff, then hand the raw response to `parse_response`.

    A parse failure (malformed base_url returning HTML instead of JSON is the common
    real-world case) becomes a non-retried ClientError — retrying an unparseable
    response never fixes it, unlike a transient TransportError.
    """
    attempt = 0
    while True:
        attempt += 1
        _notify_attempt(attempt_observer, ProviderAttempt(attempt=attempt, status="started"))
        try:
            raw = transport(request, timeout_seconds)
        except TransportError as exc:
            _notify_attempt(
                attempt_observer,
                ProviderAttempt(attempt=attempt, status="error", error_kind=exc.kind),
            )
            if exc.retryable and attempt < max_attempts:
                sleep(backoff_base_seconds * backoff_factor ** (attempt - 1))
                continue
            return ClientError(message=str(exc), kind=exc.kind, attempts=attempt)
        try:
            result = parse_response(raw)
            _notify_attempt(attempt_observer, ProviderAttempt(attempt=attempt, status="success"))
            return result
        except Exception as exc:  # noqa: BLE001 - any shape mismatch becomes a ClientError
            _notify_attempt(
                attempt_observer,
                ProviderAttempt(attempt=attempt, status="error", error_kind="invalid_request"),
            )
            return ClientError(
                message=f"Unparseable response from the endpoint: {exc}",
                kind="invalid_request",
                attempts=attempt,
            )
