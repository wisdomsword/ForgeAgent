"""Unit tests for model-id discovery/override resolution (post-M5 real-model fix).

All tests use local transports and temporary cache files — no real key, no network.
Covers: exact match, dated-snapshot fallback, unresolvable id, discovery failure,
and disk-cache reuse / manual override semantics.
"""

import json
from pathlib import Path

import anthropic
import httpx
import pytest

from forgeagent.model_discovery import (
    _pick_dated_snapshot,
    discover_provider_models,
    resolve_effective_model_id,
)


def _transport(models: list[str] | None, calls: list[str] | None = None):
    def fn(base_url: str, api_key: str) -> list[str]:
        if calls is not None:
            calls.append(base_url)
        if models is None:
            raise RuntimeError("endpoint not implemented")
        return models

    return fn


def test_discover_provider_models_returns_list():
    result = discover_provider_models(
        "https://proxy.example", "k", transport=_transport(["a", "b"])
    )
    assert result == ["a", "b"]


def test_discover_provider_models_none_on_failure():
    result = discover_provider_models("https://proxy.example", "k", transport=_transport(None))
    assert result is None


def test_discovery_uses_short_timeout_and_closes_client_on_failure(monkeypatch, tmp_path):
    sdk_class = anthropic.Anthropic
    requests = []

    def send(request):
        requests.append(request)
        raise httpx.ReadTimeout("test timeout", request=request)

    with httpx.Client(transport=httpx.MockTransport(send)) as http_client:
        monkeypatch.setattr(
            anthropic, "Anthropic", lambda **kwargs: sdk_class(http_client=http_client, **kwargs)
        )
        result = resolve_effective_model_id(
            "claude-sonnet-5",
            base_url="https://proxy.example",
            api_key="test-key",
            cache_path=tmp_path / "model_overrides.json",
        )
        assert result == "claude-sonnet-5"
        assert len(requests) == 1
        assert all(0 < limit <= 10 for limit in requests[0].extensions["timeout"].values())
        assert http_client.is_closed


@pytest.mark.parametrize("cache", [None, [], {"https://proxy.example": None}])
def test_invalid_cache_root_or_provider_is_a_miss(tmp_path, cache):
    cache_path = tmp_path / "model_overrides.json"
    cache_path.write_text(json.dumps(cache))

    assert (
        resolve_effective_model_id(
            "claude-haiku-4-5",
            base_url="https://proxy.example",
            api_key="test-key",
            cache_path=cache_path,
            transport=_transport(["claude-haiku-4-5-20251001"]),
        )
        == "claude-haiku-4-5-20251001"
    )


@pytest.mark.parametrize("invalid_model_id", [None, 42, "", "  "])
def test_invalid_cached_model_id_falls_back_to_logical_id(tmp_path, invalid_model_id):
    cache_path = tmp_path / "model_overrides.json"
    cache = {"https://proxy.example": {"claude-sonnet-5": invalid_model_id}}
    cache_path.write_text(json.dumps(cache))

    assert (
        resolve_effective_model_id(
            "claude-sonnet-5",
            base_url="https://proxy.example",
            api_key="test-key",
            cache_path=cache_path,
            transport=_transport(None),
        )
        == "claude-sonnet-5"
    )


def test_failed_cache_replacement_preserves_existing_data(monkeypatch, tmp_path):
    cache_path = tmp_path / "model_overrides.json"
    old_cache = '{"https://proxy.example": {"claude-sonnet-5": "manual-id"}}'
    cache_path.write_text(old_cache)

    def fail_to_replace(self, target):
        assert target == cache_path
        assert self.parent == cache_path.parent
        assert json.loads(self.read_text())["https://proxy.example"]["claude-haiku-4-5"] == (
            "claude-haiku-4-5-20251001"
        )
        raise OSError("cache replace failed")

    monkeypatch.setattr(Path, "replace", fail_to_replace)

    assert (
        resolve_effective_model_id(
            "claude-haiku-4-5",
            base_url="https://proxy.example",
            api_key="test-key",
            cache_path=cache_path,
            transport=_transport(["claude-haiku-4-5-20251001"]),
        )
        == "claude-haiku-4-5-20251001"
    )
    assert cache_path.read_text() == old_cache
    assert list(tmp_path.iterdir()) == [cache_path]


def test_pick_dated_snapshot_finds_match():
    assert (
        _pick_dated_snapshot("claude-haiku-4-5", ["claude-haiku-4-5-20251001", "gpt-5.5"])
        == "claude-haiku-4-5-20251001"
    )


def test_pick_dated_snapshot_picks_most_recent():
    ids = ["claude-haiku-4-5-20240101", "claude-haiku-4-5-20251001"]
    assert _pick_dated_snapshot("claude-haiku-4-5", ids) == "claude-haiku-4-5-20251001"


def test_pick_dated_snapshot_none_when_absent():
    assert _pick_dated_snapshot("claude-haiku-4-5", ["gpt-5.5"]) is None


def test_pick_dated_snapshot_does_not_match_unrelated_prefix():
    # "claude-haiku-4-5-preview" must not match the dated-snapshot pattern (no digits).
    assert _pick_dated_snapshot("claude-haiku-4-5", ["claude-haiku-4-5-preview"]) is None


def test_resolve_uses_exact_match_when_available(tmp_path):
    cache_path = tmp_path / "model_overrides.json"
    result = resolve_effective_model_id(
        "claude-sonnet-5",
        base_url="https://proxy.example",
        api_key="k",
        cache_path=cache_path,
        transport=_transport(["claude-sonnet-5", "claude-haiku-4-5-20251001"]),
    )
    assert result == "claude-sonnet-5"


def test_resolve_falls_back_to_dated_snapshot(tmp_path):
    cache_path = tmp_path / "model_overrides.json"
    result = resolve_effective_model_id(
        "claude-haiku-4-5",
        base_url="https://proxy.example",
        api_key="k",
        cache_path=cache_path,
        transport=_transport(["claude-sonnet-5", "claude-haiku-4-5-20251001"]),
    )
    assert result == "claude-haiku-4-5-20251001"


def test_resolve_unchanged_when_no_match(tmp_path):
    cache_path = tmp_path / "model_overrides.json"
    result = resolve_effective_model_id(
        "claude-opus-4-8",
        base_url="https://proxy.example",
        api_key="k",
        cache_path=cache_path,
        transport=_transport(["gpt-5.5"]),
    )
    assert result == "claude-opus-4-8"


def test_resolve_unchanged_when_discovery_fails(tmp_path):
    cache_path = tmp_path / "model_overrides.json"
    result = resolve_effective_model_id(
        "claude-haiku-4-5",
        base_url="https://proxy.example",
        api_key="k",
        cache_path=cache_path,
        transport=_transport(None),
    )
    assert result == "claude-haiku-4-5"


def test_resolve_caches_result_per_base_url(tmp_path):
    cache_path = tmp_path / "model_overrides.json"
    calls: list[str] = []
    transport = _transport(["claude-haiku-4-5-20251001"], calls=calls)

    first = resolve_effective_model_id(
        "claude-haiku-4-5",
        base_url="https://proxy.example",
        api_key="k",
        cache_path=cache_path,
        transport=transport,
    )
    second = resolve_effective_model_id(
        "claude-haiku-4-5",
        base_url="https://proxy.example",
        api_key="k",
        cache_path=cache_path,
        transport=transport,
    )
    assert first == second == "claude-haiku-4-5-20251001"
    assert len(calls) == 1  # discovery only ran once; the second call hit the cache


def test_resolve_cache_is_scoped_per_base_url(tmp_path):
    cache_path = tmp_path / "model_overrides.json"
    resolve_effective_model_id(
        "claude-haiku-4-5",
        base_url="https://proxy-a.example",
        api_key="k",
        cache_path=cache_path,
        transport=_transport(["claude-haiku-4-5-20251001"]),
    )
    result_b = resolve_effective_model_id(
        "claude-haiku-4-5",
        base_url="https://proxy-b.example",
        api_key="k",
        cache_path=cache_path,
        transport=_transport(["claude-haiku-4-5"]),  # proxy-b serves the bare alias
    )
    assert result_b == "claude-haiku-4-5"


def test_manual_override_in_cache_file_wins_without_discovery(tmp_path):
    # A user (or a prior run) can hand-edit the cache file to pin an override; a
    # transport that would raise if called proves discovery is skipped entirely.
    cache_path = tmp_path / "model_overrides.json"
    cache_path.write_text(
        json.dumps({"https://proxy.example": {"claude-haiku-4-5": "claude-haiku-4-5-pinned"}})
    )

    def exploding_transport(base_url: str, api_key: str) -> list[str]:
        raise AssertionError("discovery should not run when the cache already has an override")

    result = resolve_effective_model_id(
        "claude-haiku-4-5",
        base_url="https://proxy.example",
        api_key="k",
        cache_path=cache_path,
        transport=exploding_transport,
    )
    assert result == "claude-haiku-4-5-pinned"
