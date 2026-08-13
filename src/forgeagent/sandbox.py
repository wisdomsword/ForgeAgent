"""Validated configuration for the restricted subprocess sandbox."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictInt

DEFAULT_RESTRICTED_TIMEOUT_SECONDS = 30.0
DEFAULT_RESTRICTED_CPU_SECONDS = 10
DEFAULT_RESTRICTED_MEMORY_MB = 512
DEFAULT_CONFIG_PATH = Path.home() / ".forgeagent" / "config.yaml"


class RestrictedLimits(BaseModel):
    """Limits applied only to the ``restricted`` execution tier."""

    timeout_seconds: FiniteFloat = Field(default=DEFAULT_RESTRICTED_TIMEOUT_SECONDS, gt=0)
    cpu_seconds: StrictInt = Field(default=DEFAULT_RESTRICTED_CPU_SECONDS, gt=0)
    memory_mb: StrictInt = Field(default=DEFAULT_RESTRICTED_MEMORY_MB, gt=0)

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


def load_restricted_limits(
    path: Path | None = None,
    *,
    data: Mapping[str, object] | None = None,
) -> RestrictedLimits:
    """Load the top-level ``restricted`` mapping from the shared user config."""
    if data is None:
        config_path = DEFAULT_CONFIG_PATH if path is None else path
        if config_path.exists():
            loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if loaded is None:
                loaded = {}
        else:
            loaded = {}
    else:
        loaded = data
    if not isinstance(loaded, Mapping):
        raise ValueError("configuration root must be a mapping")
    restricted = loaded.get("restricted", {})
    if not isinstance(restricted, Mapping):
        raise ValueError("restricted must be a mapping")
    return RestrictedLimits.model_validate(restricted)


def resolve_restricted_limits(
    configured: RestrictedLimits,
    *,
    timeout_seconds: float | None = None,
    cpu_seconds: int | None = None,
    memory_mb: int | None = None,
) -> RestrictedLimits:
    """Apply explicit CLI overrides to already-validated configuration limits."""
    overrides = {
        name: value
        for name, value in {
            "timeout_seconds": timeout_seconds,
            "cpu_seconds": cpu_seconds,
            "memory_mb": memory_mb,
        }.items()
        if value is not None
    }
    if not overrides:
        return configured
    return RestrictedLimits.model_validate({**configured.model_dump(), **overrides})
