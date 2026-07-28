"""Unit tests for the local HTTP service configuration."""

from pathlib import Path

import pytest

from forgeagent.context import ContextConfig
from forgeagent.http_config import MAX_BEARER_TOKEN_LENGTH, HttpServiceConfig


@pytest.mark.parametrize(
    "token",
    [
        None,
        "",
        "   ",
        " leading",
        "trailing ",
        "middle space",
        "line\nbreak",
        "\x7f",
        "t\u00f6ken",
        123,
    ],
)
def test_http_config_rejects_unusable_token(token):
    with pytest.raises(ValueError, match="token"):
        HttpServiceConfig.from_sources(config={"port": 8765, "token": token}, env={})


def test_http_config_accepts_token_at_maximum_length():
    token = "a" * MAX_BEARER_TOKEN_LENGTH

    config = HttpServiceConfig.from_sources(config={"token": token}, env={})

    assert config.token == token


def test_http_config_rejects_token_over_maximum_length():
    token = "a" * (MAX_BEARER_TOKEN_LENGTH + 1)

    with pytest.raises(ValueError, match="token.*4096"):
        HttpServiceConfig.from_sources(config={"token": token}, env={})


def test_http_config_repr_does_not_include_token():
    token = "sensitive-http-token"

    config = HttpServiceConfig.from_sources(config={"token": token}, env={})

    assert token not in repr(config)


def test_http_config_rejects_non_loopback():
    with pytest.raises(ValueError, match="loopback"):
        HttpServiceConfig.from_sources(
            config={"bind_host": "0.0.0.0", "token": "file-token"}, env={}
        )


def test_http_config_environment_token_wins_and_other_values_are_configurable():
    config = HttpServiceConfig.from_sources(
        config={
            "bind_host": "::1",
            "port": 9000,
            "token": "file-token",
            "max_workers": 2,
            "max_queue": 8,
            "max_records": 64,
            "terminal_ttl_seconds": 120.0,
            "max_body_bytes": 4096,
            "audit_path": "/tmp/forgeagent-audit.jsonl",
            "audit_max_bytes": 8192,
            "audit_retention_files": 3,
            "allowlist": ["server/tool"],
        },
        env={"FORGEAGENT_HTTP_TOKEN": "env-token"},
    )

    assert config == HttpServiceConfig(
        bind_host="::1",
        port=9000,
        token="env-token",
        max_workers=2,
        max_queue=8,
        max_records=64,
        terminal_ttl_seconds=120.0,
        max_body_bytes=4096,
        audit_path=Path("/tmp/forgeagent-audit.jsonl"),
        audit_max_bytes=8192,
        audit_retention_files=3,
        allowlist=("server/tool",),
    )


def test_http_config_preserves_direct_pathlike_audit_path(tmp_path):
    audit_path = tmp_path / "events.jsonl"

    config = HttpServiceConfig.from_sources(
        config={"token": "secret", "audit_path": audit_path},
        env={},
    )

    assert config.audit_path == audit_path


@pytest.mark.parametrize(
    "audit_path",
    [None, True, 1, 1.5, [], {}, b"audit.jsonl", "", "   \t"],
)
def test_http_config_rejects_invalid_audit_path_types_and_blank_strings(audit_path):
    with pytest.raises(ValueError, match="audit_path"):
        HttpServiceConfig.from_sources(
            config={"token": "secret", "audit_path": audit_path},
            env={},
        )


def test_http_config_uses_documented_defaults():
    config = HttpServiceConfig.from_sources(config={"token": "secret"}, env={})

    assert config == HttpServiceConfig(token="secret")
    assert config.evaluator_tier == "restricted"
    assert config.max_rejections == 2
    assert config.triad_plan_policy == "deny"
    assert config.allow_weaker_override is False


def test_http_config_accepts_server_owned_collaboration_policy():
    config = HttpServiceConfig.from_sources(
        config={
            "token": "secret",
            "planner_model": "planner-model",
            "evaluator_model": "evaluator-model",
            "evaluator_tier": "container",
            "max_rejections": 4,
            "triad_plan_policy": "preauthorize",
            "allow_weaker_override": True,
        },
        env={},
    )

    assert config.planner_model == "planner-model"
    assert config.evaluator_model == "evaluator-model"
    assert config.evaluator_tier == "container"
    assert config.max_rejections == 4
    assert config.triad_plan_policy == "preauthorize"
    assert config.allow_weaker_override is True


def test_http_config_rejects_client_forgeable_bound_checks_fact():
    with pytest.raises(ValueError, match="has_bound_checks"):
        HttpServiceConfig.from_sources(config={"token": "secret", "has_bound_checks": True}, env={})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evaluator_tier", "trusted"),
        ("max_rejections", True),
        ("max_rejections", 0),
        ("triad_plan_policy", "ask"),
        ("allow_weaker_override", 1),
        ("planner_model", ""),
        ("evaluator_model", "bad\nmodel"),
    ],
)
def test_http_config_rejects_invalid_collaboration_policy(field, value):
    with pytest.raises(ValueError, match=field):
        HttpServiceConfig.from_sources(config={"token": "secret", field: value}, env={})


def test_http_config_owns_validated_context_defaults_and_explicit_values():
    default_config = HttpServiceConfig.from_sources(config={"token": "secret"}, env={})
    configured = HttpServiceConfig.from_sources(
        config={
            "token": "secret",
            "context": {
                "utilization_ratio": 0.75,
                "image_token_reserve": 512,
                "tool_result_max_tokens": 20,
                "round_feedback_max_tokens": 40,
            },
        },
        env={},
    )

    assert default_config.context_config == ContextConfig()
    assert configured.context_config == ContextConfig(
        utilization_ratio=0.75,
        image_token_reserve=512,
        tool_result_max_tokens=20,
        round_feedback_max_tokens=40,
    )


@pytest.mark.parametrize(
    "context",
    [
        [],
        {"utilization_ratio": 8},
        {"image_token_reserve": 0},
        {"unknown": 1},
        {"tool_result_max_tokens": 20, "round_feedback_max_tokens": 10},
    ],
)
def test_http_config_rejects_invalid_context_mapping(context):
    with pytest.raises(ValueError, match="context"):
        HttpServiceConfig.from_sources(config={"token": "secret", "context": context}, env={})


@pytest.mark.parametrize("allowlist", ["server/tool", b"server/tool"])
def test_http_config_rejects_string_like_allowlist(allowlist):
    with pytest.raises(ValueError, match="allowlist"):
        HttpServiceConfig.from_sources(config={"token": "secret", "allowlist": allowlist}, env={})


@pytest.mark.parametrize("allowlist", [[123], [b"server/tool"], [""], ["   "]])
def test_http_config_rejects_invalid_allowlist_items(allowlist):
    with pytest.raises(ValueError, match="allowlist"):
        HttpServiceConfig.from_sources(config={"token": "secret", "allowlist": allowlist}, env={})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("port", 0),
        ("port", 65536),
        ("max_workers", 0),
        ("max_queue", -1),
        ("max_records", 0),
        ("terminal_ttl_seconds", 0),
        ("max_body_bytes", 0),
        ("audit_max_bytes", 0),
        ("audit_retention_files", 0),
    ],
)
def test_http_config_rejects_out_of_range_limits(field, value):
    with pytest.raises(ValueError, match=field):
        HttpServiceConfig.from_sources(config={"token": "secret", field: value}, env={})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_http_config_rejects_non_finite_terminal_ttl(value):
    with pytest.raises(ValueError, match="terminal_ttl_seconds"):
        HttpServiceConfig.from_sources(
            config={"token": "secret", "terminal_ttl_seconds": value}, env={}
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("port", "8765"),
        ("port", 8765.0),
        ("port", True),
        ("max_workers", 1.9),
        ("max_workers", False),
        ("max_queue", 1.9),
        ("max_queue", True),
        ("max_records", 2.5),
        ("max_body_bytes", 1024.5),
        ("audit_max_bytes", 100.9),
        ("audit_retention_files", 2.5),
    ],
)
def test_http_config_rejects_non_integer_limit_types(field, value):
    with pytest.raises(ValueError, match=field):
        HttpServiceConfig.from_sources(config={"token": "secret", field: value}, env={})


@pytest.mark.parametrize("value", [True, False, "1.5"])
def test_http_config_rejects_non_numeric_terminal_ttl_types(value):
    with pytest.raises(ValueError, match="terminal_ttl_seconds"):
        HttpServiceConfig.from_sources(
            config={"token": "secret", "terminal_ttl_seconds": value}, env={}
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("port", 1),
        ("port", 65535),
        ("max_workers", 1),
        ("max_queue", 0),
        ("max_records", 1),
        ("terminal_ttl_seconds", 0.1),
        ("max_body_bytes", 1),
        ("audit_max_bytes", 1),
        ("audit_retention_files", 1),
    ],
)
def test_http_config_accepts_limit_boundaries(field, value):
    config = HttpServiceConfig.from_sources(config={"token": "secret", field: value}, env={})

    assert getattr(config, field) == value
