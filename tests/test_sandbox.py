"""Restricted sandbox configuration tests."""

from pathlib import Path

import pytest

from forgeagent.sandbox import RestrictedLimits, load_restricted_limits, resolve_restricted_limits


def test_restricted_limits_load_from_shared_config_mapping(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "groups: {}\ncontext: {}\nrestricted:\n  timeout_seconds: 4.5\n"
        "  cpu_seconds: 3\n  memory_mb: 256\n",
        encoding="utf-8",
    )

    assert load_restricted_limits(path) == RestrictedLimits(
        timeout_seconds=4.5, cpu_seconds=3, memory_mb=256
    )


def test_explicit_limit_values_override_configured_values():
    configured = RestrictedLimits(timeout_seconds=4.5, cpu_seconds=3, memory_mb=256)

    assert resolve_restricted_limits(
        configured, timeout_seconds=9.0, memory_mb=768
    ) == RestrictedLimits(timeout_seconds=9.0, cpu_seconds=3, memory_mb=768)


@pytest.mark.parametrize(
    "config",
    [
        {"restricted": {"timeout_seconds": 0}},
        {"restricted": {"cpu_seconds": "3"}},
        {"restricted": {"memory_mb": 0}},
        {"restricted": {"unknown": 1}},
    ],
)
def test_restricted_limits_reject_invalid_values(config):
    with pytest.raises(ValueError):
        load_restricted_limits(data=config)
