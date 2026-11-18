"""Model-id discovery and override resolution for Anthropic-compatible proxies.

Some third-party proxies only serve a model under a dated snapshot id (e.g.
"claude-haiku-4-5-20251001") and reject the bare alias ("claude-haiku-4-5") with a
routing error, even though both names refer to the same capability. This module
queries the provider's `/v1/models` endpoint and, when the registry's logical id is
absent but a dated snapshot of it is present, resolves to that snapshot instead — with
no per-provider branching in the caller (see docs/model-client-contract.md
capability-gating: callers never branch on model name or provider).

Resolutions are cached to disk per base_url (DEFAULT_CACHE_PATH), so discovery only
happens once per provider. The cache file is also the "local override config" a user
can hand-edit: adding `{"<base_url>": {"<logical_id>": "<actual_id>"}}` pins an
override without waiting for discovery. Discovery failures (endpoint not implemented,
network error) are non-fatal — the logical id is used unchanged and the real request
surfaces whatever the provider actually says.
"""

from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

# (base_url, api_key) -> list of model id strings the provider serves.
ModelListTransport = Callable[[str, str], list[str]]

DEFAULT_BASE_URL = "https://api.anthropic.com"
DEFAULT_CACHE_PATH = Path.home() / ".forgeagent" / "model_overrides.json"

_DISCOVERY_TIMEOUT_SECONDS = 5.0
_DATED_SNAPSHOT_RE_TEMPLATE = r"^{}-\d+$"


def _make_sdk_transport(timeout_seconds: float) -> ModelListTransport:
    """Default transport: list models via the Anthropic SDK against base_url."""

    def transport(base_url: str, api_key: str) -> list[str]:
        import anthropic

        with anthropic.Anthropic(
            api_key=api_key, base_url=base_url, timeout=timeout_seconds, max_retries=0
        ) as client:
            return [model.id for model in client.models.list().data]

    return transport


def discover_provider_models(
    base_url: str,
    api_key: str,
    *,
    transport: ModelListTransport | None = None,
    timeout_seconds: float = _DISCOVERY_TIMEOUT_SECONDS,
) -> list[str] | None:
    """List the model ids `base_url` actually serves, or None if discovery failed.

    None (not an empty list) signals "couldn't ask" — e.g. the proxy doesn't
    implement /v1/models — distinct from "asked, got zero models".
    """
    transport = transport or _make_sdk_transport(min(timeout_seconds, _DISCOVERY_TIMEOUT_SECONDS))
    try:
        return transport(base_url, api_key)
    except Exception:
        return None


def _pick_dated_snapshot(logical_id: str, available_ids: list[str]) -> str | None:
    """Find a dated-snapshot id of `logical_id` (e.g. "<id>-20251001") among

    `available_ids`, returning the lexicographically greatest (= most recent, since
    the date suffix is YYYYMMDD) match, or None if there is no such snapshot.
    """
    pattern = re.compile(_DATED_SNAPSHOT_RE_TEMPLATE.format(re.escape(logical_id)))
    matches = [m for m in available_ids if pattern.match(m)]
    return max(matches) if matches else None


def _load_cache(cache_path: Path) -> dict[str, dict[str, str]]:
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return {}
    if not isinstance(cache, dict):
        return {}
    return {
        provider: {
            logical_id: effective_id
            for logical_id, effective_id in overrides.items()
            if isinstance(effective_id, str) and effective_id.strip()
        }
        for provider, overrides in cache.items()
        if isinstance(overrides, dict)
    }


def _save_cache(cache_path: Path, cache: dict[str, dict[str, str]]) -> None:
    temporary_path: Path | None = None
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=cache_path.parent, delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(cache, temporary_file, indent=2, sort_keys=True)
        temporary_path.replace(cache_path)
        temporary_path = None
    except OSError:
        pass  # best-effort: a cache write failure must never break a real call
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink()


def resolve_effective_model_id(
    logical_id: str,
    *,
    base_url: str | None,
    api_key: str,
    cache_path: Path | None = None,
    transport: ModelListTransport | None = None,
    timeout_seconds: float = _DISCOVERY_TIMEOUT_SECONDS,
) -> str:
    """Return the model id to actually send to `base_url` for `logical_id`.

    Checks the per-base_url disk cache first (also the manual override file — see
    module docstring); on a miss, discovers the provider's model list and looks for an
    exact match or a dated snapshot of `logical_id`. Any failure to discover or
    resolve falls back to `logical_id` unchanged, so the request then succeeds or
    fails exactly as it would have without this layer.
    """
    effective_base_url = base_url or DEFAULT_BASE_URL
    cache_path = cache_path or DEFAULT_CACHE_PATH
    cache = _load_cache(cache_path)
    provider_overrides = cache.get(effective_base_url, {})

    if logical_id in provider_overrides:
        return provider_overrides[logical_id]

    available = discover_provider_models(
        effective_base_url, api_key, transport=transport, timeout_seconds=timeout_seconds
    )
    if available is None:
        return logical_id  # discovery unavailable; use the logical id unchanged

    effective = (
        logical_id
        if logical_id in available
        else (_pick_dated_snapshot(logical_id, available) or logical_id)
    )

    provider_overrides[logical_id] = effective
    cache[effective_base_url] = provider_overrides
    _save_cache(cache_path, cache)
    return effective
