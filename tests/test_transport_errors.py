"""Unit tests for the shared transport-exception classification module (M6).

anthropic_client.py and openai_compatible_client.py both import
classify_transport_exception/TransportError from here (see transport_errors.py's
docstring) — these tests cover the shared module directly, complementing the
per-client indirect coverage in test_anthropic_client.py/test_openai_compatible_client.py.
"""

import pytest

from forgeagent.transport_errors import TransportError, classify_transport_exception


# Stub exceptions whose __name__ matches the SDK class names the classifier keys on
# (matched by class name via MRO, so the names must be exact).
class APITimeoutError(Exception):
    pass


class APIConnectionError(Exception):
    pass


class RateLimitError(Exception):
    pass


class InternalServerError(Exception):
    pass


class AuthenticationError(Exception):
    pass


class PermissionDeniedError(Exception):
    pass


class BadRequestError(Exception):
    pass


class UnprocessableEntityError(Exception):
    pass


class SomeVendorSpecificSubclassOfBadRequestError(BadRequestError):
    pass


@pytest.mark.parametrize(
    "exc,expected",
    [
        (APITimeoutError(), ("timeout", True)),
        (APIConnectionError(), ("network", True)),
        (RateLimitError(), ("rate_limit", True)),
        (InternalServerError(), ("network", True)),
        (AuthenticationError(), ("auth", False)),
        (PermissionDeniedError(), ("auth", False)),
        (BadRequestError(), ("invalid_request", False)),
        (UnprocessableEntityError(), ("invalid_request", False)),
    ],
)
def test_classify_known_exception_names(exc, expected):
    assert classify_transport_exception(exc) == expected


def test_classify_unknown_exception_is_unknown_not_retryable():
    assert classify_transport_exception(ValueError("x")) == ("unknown", False)


def test_classify_matches_via_mro_not_just_exact_type():
    # A vendor SDK subclass of a known exception name still classifies correctly,
    # since matching walks the full MRO, not just type(exc).__name__.
    assert classify_transport_exception(SomeVendorSpecificSubclassOfBadRequestError()) == (
        "invalid_request",
        False,
    )


def test_transport_error_carries_kind_and_retryable():
    exc = TransportError("network", True, "conn reset")
    assert exc.kind == "network"
    assert exc.retryable is True
    assert str(exc) == "conn reset"
