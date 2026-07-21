"""Unit tests for the local HTTP service configuration."""

from pathlib import Path

import pytest

from forgeagent.http_config import HttpServiceConfig


@pytest.mark.parametrize("token", [None, "", "   "])
def test_http_config_rejects_missing_or_blank_token(token):
    with pytest.raises(ValueError, match="token"):
        HttpServiceConfig.from_sources(config={"port": 8765, "token": token}, env={})


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
