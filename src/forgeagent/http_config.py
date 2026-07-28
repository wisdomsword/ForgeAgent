"""Validated configuration for the local HTTP task service."""

from __future__ import annotations

import ipaddress
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from dataclasses import field as dataclass_field
from pathlib import Path

from .context import ContextConfig

MAX_BEARER_TOKEN_LENGTH = 4096


def _integer_value(values: Mapping[str, object], field: str, default: int) -> int:
    value = values.get(field, default)
    if type(value) is not int:
        raise ValueError(f"{field} must be an integer")
    return value


def _finite_number_value(values: Mapping[str, object], field: str, default: float) -> float:
    value = values.get(field, default)
    if type(value) not in {int, float}:
        raise ValueError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _path_value(values: Mapping[str, object], field: str, default: str | os.PathLike[str]) -> Path:
    value = values.get(field, default)
    if isinstance(value, str):
        raw_path = value
    elif isinstance(value, os.PathLike):
        try:
            raw_path = os.fspath(value)
        except (TypeError, ValueError, OSError) as error:
            raise ValueError(f"{field} must be a non-empty path") from error
        if not isinstance(raw_path, str):
            raise ValueError(f"{field} must be a non-empty path")
    else:
        raise ValueError(f"{field} must be a non-empty path")
    if not raw_path.strip():
        raise ValueError(f"{field} must be a non-empty path")
    return Path(raw_path)


@dataclass(frozen=True)
class HttpServiceConfig:
    """Server-owned limits and credentials for the loopback-only HTTP service."""

    bind_host: str = "127.0.0.1"
    port: int = 8765
    token: str = dataclass_field(default="", repr=False)
    max_workers: int = 4
    max_queue: int = 32
    max_records: int = 256
    terminal_ttl_seconds: float = 3600.0
    max_body_bytes: int = 64 * 1024
    audit_path: Path = Path("~/.forgeagent/http-audit.jsonl")
    audit_max_bytes: int = 10 * 1024 * 1024
    audit_retention_files: int = 5
    allowlist: tuple[str, ...] = ()
    context_config: ContextConfig = dataclass_field(default_factory=ContextConfig)
    planner_model: str = ""
    evaluator_model: str = ""
    evaluator_tier: str = "restricted"
    max_rejections: int = 2
    triad_plan_policy: str = "deny"
    allow_weaker_override: bool = False

    @classmethod
    def from_sources(
        cls,
        config: Mapping[str, object] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> HttpServiceConfig:
        """Build config with the dedicated token environment variable taking priority."""
        values = dict(config or {})
        unknown_fields = set(values) - {
            *(field.name for field in fields(cls) if field.name != "context_config"),
            "context",
        }
        if unknown_fields:
            names = ", ".join(sorted(unknown_fields))
            raise ValueError(f"unknown HTTP service configuration fields: {names}")
        source_env = os.environ if env is None else env
        token = source_env.get("FORGEAGENT_HTTP_TOKEN", values.get("token", ""))
        host = str(values.get("bind_host", "127.0.0.1"))
        allowlist = values.get("allowlist", ())
        context_value = values.get("context", {})

        planner_model = values.get("planner_model", "")
        evaluator_model = values.get("evaluator_model", "")
        for field_name, value in (
            ("planner_model", planner_model),
            ("evaluator_model", evaluator_model),
        ):
            if not isinstance(value, str) or any(ord(character) < 32 for character in value):
                raise ValueError(f"{field_name} must be a valid model id")
            if field_name in values and not value.strip():
                raise ValueError(f"{field_name} must be a valid model id")
        evaluator_tier = values.get("evaluator_tier", "restricted")
        if evaluator_tier not in {"restricted", "container"}:
            raise ValueError("evaluator_tier must be restricted or container")
        max_rejections = _integer_value(values, "max_rejections", 2)
        if not 1 <= max_rejections <= 10:
            raise ValueError("max_rejections must be between 1 and 10")
        triad_plan_policy = values.get("triad_plan_policy", "deny")
        if triad_plan_policy not in {"deny", "preauthorize"}:
            raise ValueError("triad_plan_policy must be deny or preauthorize")
        allow_weaker_override = values.get("allow_weaker_override", False)
        if type(allow_weaker_override) is not bool:
            raise ValueError("allow_weaker_override must be a bool")

        try:
            if not isinstance(context_value, Mapping):
                raise ValueError
            context_config = ContextConfig.model_validate(context_value)
        except ValueError as error:
            raise ValueError("context configuration is invalid") from error

        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError as exc:
            raise ValueError("HTTP service must bind to a loopback IP address") from exc
        if not is_loopback:
            raise ValueError("HTTP service must bind to loopback")
        if (
            not isinstance(token, str)
            or not token
            or len(token) > MAX_BEARER_TOKEN_LENGTH
            or not token.isascii()
            or not token.isprintable()
            or any(character.isspace() for character in token)
        ):
            raise ValueError(
                "HTTP bearer token must be a non-whitespace printable ASCII string "
                f"of at most {MAX_BEARER_TOKEN_LENGTH} characters"
            )
        if isinstance(allowlist, (str, bytes)) or not isinstance(allowlist, Sequence):
            raise ValueError("allowlist must be a sequence of non-empty strings")
        if any(not isinstance(item, str) or not item.strip() for item in allowlist):
            raise ValueError("allowlist must contain only non-empty strings")

        result = cls(
            bind_host=host,
            port=_integer_value(values, "port", 8765),
            token=token,
            max_workers=_integer_value(values, "max_workers", 4),
            max_queue=_integer_value(values, "max_queue", 32),
            max_records=_integer_value(values, "max_records", 256),
            terminal_ttl_seconds=_finite_number_value(values, "terminal_ttl_seconds", 3600.0),
            max_body_bytes=_integer_value(values, "max_body_bytes", 64 * 1024),
            audit_path=_path_value(
                values,
                "audit_path",
                Path("~/.forgeagent/http-audit.jsonl"),
            ),
            audit_max_bytes=_integer_value(values, "audit_max_bytes", 10 * 1024 * 1024),
            audit_retention_files=_integer_value(values, "audit_retention_files", 5),
            allowlist=tuple(allowlist),
            context_config=context_config,
            planner_model=planner_model,
            evaluator_model=evaluator_model,
            evaluator_tier=evaluator_tier,
            max_rejections=max_rejections,
            triad_plan_policy=triad_plan_policy,
            allow_weaker_override=allow_weaker_override,
        )
        if not 1 <= result.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        for limit_field in (
            "max_workers",
            "max_records",
            "terminal_ttl_seconds",
            "max_body_bytes",
            "audit_max_bytes",
            "audit_retention_files",
        ):
            if getattr(result, limit_field) <= 0:
                raise ValueError(f"{limit_field} must be greater than zero")
        if result.max_queue < 0:
            raise ValueError("max_queue must not be negative")
        return result
