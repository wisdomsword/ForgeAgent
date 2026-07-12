"""Unit tests for the YAML-based model/provider registry (M6 follow-up).

Replaces test_capabilities.py + test_config.py. Two built-in files, two concerns:
models.yaml (capabilities + aliases) and config.yaml (provider groups + routing) —
kept separate so extending one never means redeclaring the other. The core
regression this guards against: routing must be by the model's own registered
group, never a priority scan across whichever provider's env vars happen to be set
(see model_registry.py docstring) — a real bug found via live smoke testing where a
gpt-5.4-mini request was silently routed to an unrelated LLM_* gateway because
LLM_API_KEY was also set.
"""

import pytest
import yaml

from forgeagent.model_registry import (
    RegistryError,
    list_models,
    load_registry,
    reload_registry,
    resolve_model,
)

# Expected values transcribed from docs/model-capability-matrix.md /
# docs/m6-openai-compatible-client.md — guards against models.yaml drifting from docs.
EXPECTED_ANTHROPIC = {
    "claude-sonnet-5": (1_000_000, 128_000, True, False, True),
    "claude-opus-4-8": (1_000_000, 128_000, True, False, True),
    "claude-haiku-4-5": (200_000, 64_000, False, False, False),
    "claude-fable-5": (1_000_000, 128_000, True, True, True),
}
EXPECTED_OPENAI_COMPATIBLE = {
    "gpt-5.5": (1_050_000, 128_000, False, False, True, "max_completion_tokens"),
    "gpt-5.4-mini": (400_000, 128_000, False, False, True, "max_completion_tokens"),
    "glm-5.2": (1_048_576, 131_072, True, False, True, "max_tokens"),
    "deepseek-v4-flash": (1_000_000, 384_000, True, False, True, "max_tokens"),
}


def _registry(tmp_path, **user_files):
    """Load the built-in registry with user override paths pointed at tmp_path
    (missing by default, so tests never read the real ~/.forgeagent files)."""
    return load_registry(
        user_models_path=user_files.get("models_path", tmp_path / "no-models.yaml"),
        user_config_path=user_files.get("config_path", tmp_path / "no-config.yaml"),
    )


@pytest.mark.parametrize("model_id", list(EXPECTED_ANTHROPIC))
def test_builtin_anthropic_capability_values_match_matrix(tmp_path, model_id):
    ctx, max_out, thinking, thinking_always, effort = EXPECTED_ANTHROPIC[model_id]
    registry = _registry(tmp_path)
    resolved = resolve_model(model_id, registry, env={"ANTHROPIC_API_KEY": "k"})
    cap = resolved.capability
    assert cap.context_window == ctx
    assert cap.max_output_tokens == max_out
    assert cap.supports_thinking is thinking
    assert cap.thinking_always_on is thinking_always
    assert cap.supports_effort is effort
    assert cap.client_kind == "anthropic"
    assert cap.max_tokens_param == "max_tokens"


@pytest.mark.parametrize("model_id", list(EXPECTED_OPENAI_COMPATIBLE))
def test_builtin_openai_compatible_capability_values_match_docs(tmp_path, model_id):
    ctx, max_out, thinking, thinking_always, effort, max_tokens_param = EXPECTED_OPENAI_COMPATIBLE[
        model_id
    ]
    registry = _registry(tmp_path)
    resolved = resolve_model(model_id, registry, env={"OPENAI_API_KEY": "k", "LLM_API_KEY": "k"})
    cap = resolved.capability
    assert cap.context_window == ctx
    assert cap.max_output_tokens == max_out
    assert cap.supports_thinking is thinking
    assert cap.thinking_always_on is thinking_always
    assert cap.supports_effort is effort
    assert cap.client_kind == "openai_compatible"
    assert cap.max_tokens_param == max_tokens_param


def test_unknown_model_raises_with_known_list(tmp_path):
    registry = _registry(tmp_path)
    with pytest.raises(RegistryError, match="Unknown model id"):
        resolve_model("gpt-6-ultra-unregistered", registry, env={})


def test_default_model_from_builtin_registry(tmp_path):
    registry = _registry(tmp_path)
    assert registry.default_model == "claude-sonnet-5"


# --- aliases -------------------------------------------------------------------


def test_alias_resolves_to_canonical_model(tmp_path):
    registry = _registry(tmp_path)
    resolved = resolve_model("sonnet", registry, env={"ANTHROPIC_API_KEY": "k"})
    assert resolved.capability.model_id == "claude-sonnet-5"


def test_alias_collision_raises(tmp_path):
    models_path = tmp_path / "models.yaml"
    models_path.write_text(
        yaml.safe_dump(
            {
                "models": {
                    "claude-haiku-4-5": {"aliases": ["sonnet"]},
                }
            }
        )
    )
    with pytest.raises(RegistryError, match="collides"):
        _registry(tmp_path, models_path=models_path)


# --- exact routing: the actual bug this refactor fixes -----------------------


def test_routes_to_requested_models_own_group_even_when_other_keys_set(tmp_path):
    # gpt-5.4-mini belongs to the openai group; LLM_API_KEY being set (for an
    # unrelated gateway) must have zero effect on this resolution.
    registry = _registry(tmp_path)
    resolved = resolve_model(
        "gpt-5.4-mini",
        registry,
        env={
            "OPENAI_API_KEY": "openai-key",
            "LLM_API_KEY": "llm-key",
            "LLM_BASE_URL": "https://wrong.example",
        },
    )
    assert resolved.api_key == "openai-key"
    assert resolved.base_url is None  # OPENAI_BASE_URL not set; LLM_BASE_URL must not leak in


def test_routes_llm_group_model_using_only_llm_env(tmp_path):
    registry = _registry(tmp_path)
    resolved = resolve_model(
        "glm-5.2",
        registry,
        env={
            "LLM_API_KEY": "llm-key",
            "LLM_BASE_URL": "https://gateway.example/v1",
            "OPENAI_API_KEY": "openai-key",
        },
    )
    assert resolved.api_key == "llm-key"
    assert resolved.base_url == "https://gateway.example/v1"


def test_missing_key_raises_registry_error(tmp_path):
    registry = _registry(tmp_path)
    with pytest.raises(RegistryError, match="OPENAI_API_KEY"):
        resolve_model("gpt-5.4-mini", registry, env={})


# --- user override files -------------------------------------------------------


def test_user_models_override_adds_new_model(tmp_path):
    models_path = tmp_path / "models.yaml"
    models_path.write_text(
        yaml.safe_dump(
            {
                "models": {
                    "acme-mini": {
                        "client_kind": "openai_compatible",
                        "context_window": 32_000,
                        "max_output_tokens": 4_000,
                        "supports_thinking": False,
                        "thinking_always_on": False,
                        "supports_effort": False,
                    }
                }
            }
        )
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {"groups": {"acme": {"api_key_env": "ACME_API_KEY", "models": ["acme-mini"]}}}
        )
    )
    registry = _registry(tmp_path, models_path=models_path, config_path=config_path)
    resolved = resolve_model("acme-mini", registry, env={"ACME_API_KEY": "acme-key"})
    assert resolved.api_key == "acme-key"
    assert resolved.capability.context_window == 32_000


def test_user_config_can_add_model_to_existing_builtin_group(tmp_path):
    models_path = tmp_path / "models.yaml"
    models_path.write_text(
        yaml.safe_dump(
            {
                "models": {
                    "claude-new-model": {
                        "client_kind": "anthropic",
                        "context_window": 500_000,
                        "max_output_tokens": 64_000,
                        "supports_thinking": True,
                        "thinking_always_on": False,
                        "supports_effort": True,
                    }
                }
            }
        )
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump({"groups": {"anthropic": {"models": ["claude-new-model"]}}})
    )
    registry = _registry(tmp_path, models_path=models_path, config_path=config_path)
    # Pre-existing builtin model in the same group must still resolve.
    resolved = resolve_model("claude-sonnet-5", registry, env={"ANTHROPIC_API_KEY": "k"})
    assert resolved.capability.model_id == "claude-sonnet-5"
    resolved_new = resolve_model("claude-new-model", registry, env={"ANTHROPIC_API_KEY": "k"})
    assert resolved_new.capability.context_window == 500_000


def test_user_config_literal_api_key_takes_precedence_over_env(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump({"groups": {"anthropic": {"api_key": "sk-literal-from-file"}}})
    )
    registry = _registry(tmp_path, config_path=config_path)
    resolved = resolve_model("claude-sonnet-5", registry, env={"ANTHROPIC_API_KEY": "sk-from-env"})
    assert resolved.api_key == "sk-literal-from-file"


def test_user_config_literal_base_url_takes_precedence_over_env(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump({"groups": {"anthropic": {"base_url": "https://literal.example"}}})
    )
    registry = _registry(tmp_path, config_path=config_path)
    resolved = resolve_model(
        "claude-sonnet-5",
        registry,
        env={"ANTHROPIC_API_KEY": "k", "ANTHROPIC_BASE_URL": "https://from-env.example"},
    )
    assert resolved.base_url == "https://literal.example"


def test_missing_user_files_are_silently_skipped(tmp_path):
    registry = _registry(tmp_path)
    resolved = resolve_model("claude-sonnet-5", registry, env={"ANTHROPIC_API_KEY": "k"})
    assert resolved.capability.model_id == "claude-sonnet-5"


# --- validation: model<->group consistency -------------------------------------


def test_model_listed_in_two_groups_raises(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "groups": {
                    "duplicate-group": {
                        "api_key_env": "DUP_API_KEY",
                        "models": ["claude-sonnet-5"],
                    }
                }
            }
        )
    )
    with pytest.raises(RegistryError, match="only be routed through one group"):
        _registry(tmp_path, config_path=config_path)


def test_group_listing_unknown_model_raises(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump({"groups": {"anthropic": {"models": ["claude-sonnet-5", "no-such-model"]}}})
    )
    with pytest.raises(RegistryError, match="no capability entry"):
        _registry(tmp_path, config_path=config_path)


def test_malformed_models_yaml_raises_registry_error(tmp_path):
    # A model entry missing a required field (context_window) must fail pydantic
    # validation, but callers should only ever see RegistryError, never a raw
    # pydantic ValidationError (cli.py only catches RegistryError).
    models_path = tmp_path / "models.yaml"
    models_path.write_text(
        yaml.safe_dump(
            {
                "models": {
                    "broken-model": {
                        "client_kind": "anthropic",
                        "max_output_tokens": 1,
                        "supports_thinking": False,
                        "thinking_always_on": False,
                        "supports_effort": False,
                    }
                }
            }
        )
    )
    with pytest.raises(RegistryError, match="Malformed models.yaml or config.yaml"):
        _registry(tmp_path, models_path=models_path)


def test_group_with_no_api_key_env_gives_actionable_message(tmp_path):
    # A group with neither api_key nor api_key_env configured must not print the
    # confusing "Set the 'None' environment variable" message.
    models_path = tmp_path / "models.yaml"
    models_path.write_text(
        yaml.safe_dump(
            {
                "models": {
                    "acme-mini": {
                        "client_kind": "openai_compatible",
                        "context_window": 32_000,
                        "max_output_tokens": 4_000,
                        "supports_thinking": False,
                        "thinking_always_on": False,
                        "supports_effort": False,
                    }
                }
            }
        )
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"groups": {"acme": {"models": ["acme-mini"]}}}))
    registry = _registry(tmp_path, models_path=models_path, config_path=config_path)
    with pytest.raises(RegistryError, match="no api_key_env configured"):
        resolve_model("acme-mini", registry, env={})


def test_model_with_capability_but_no_group_raises(tmp_path):
    models_path = tmp_path / "models.yaml"
    models_path.write_text(
        yaml.safe_dump(
            {
                "models": {
                    "orphan-model": {
                        "client_kind": "anthropic",
                        "context_window": 1,
                        "max_output_tokens": 1,
                        "supports_thinking": False,
                        "thinking_always_on": False,
                        "supports_effort": False,
                    }
                }
            }
        )
    )
    registry = _registry(tmp_path, models_path=models_path)
    with pytest.raises(RegistryError, match="not listed under any group"):
        resolve_model("orphan-model", registry, env={})


# --- alias index / reload / list_models (M7 Phase 4) -------------------------


def test_alias_index_precomputed_and_covers_all_aliases(tmp_path):
    # The alias index is built at load time and maps every declared alias to its canonical
    # model — so _resolve_alias is an O(1) dict lookup, not a per-call linear scan.
    registry = _registry(tmp_path)
    assert registry.alias_index["sonnet"] == "claude-sonnet-5"
    assert registry.alias_index["haiku"] == "claude-haiku-4-5"
    assert registry.alias_index["deepseek"] == "deepseek-v4-flash"
    # Every alias declared on a model appears in the index pointing back at that model.
    for model_id, entry in registry.models.items():
        for alias in entry.aliases:
            assert registry.alias_index[alias] == model_id


def test_alias_index_resolution_matches_prior_behaviour(tmp_path):
    # The O(1) index resolves aliases identically to the old scan (regression guard).
    registry = _registry(tmp_path)
    resolved = resolve_model("sonnet", registry, env={"ANTHROPIC_API_KEY": "k"})
    assert resolved.capability.model_id == "claude-sonnet-5"


def test_reload_registry_reflects_file_changes(tmp_path):
    # reload re-reads from disk: an alias absent at first load appears after the user file
    # gains it — no process restart needed.
    models_path = tmp_path / "models.yaml"
    config_path = tmp_path / "no-config.yaml"
    models_path.write_text(yaml.safe_dump({"models": {"claude-sonnet-5": {"aliases": []}}}))
    first = reload_registry(user_models_path=models_path, user_config_path=config_path)
    assert "s5" not in first.alias_index

    models_path.write_text(yaml.safe_dump({"models": {"claude-sonnet-5": {"aliases": ["s5"]}}}))
    second = reload_registry(user_models_path=models_path, user_config_path=config_path)
    assert second.alias_index["s5"] == "claude-sonnet-5"


def test_list_models_returns_all_models_sorted_with_fields(tmp_path):
    registry = _registry(tmp_path)
    infos = list_models(registry)
    ids = [i.model_id for i in infos]
    assert ids == sorted(ids)  # sorted by model_id
    assert set(ids) == set(registry.models)  # covers every registered model
    sonnet = next(i for i in infos if i.model_id == "claude-sonnet-5")
    assert "sonnet" in sonnet.aliases
    assert sonnet.client_kind == "anthropic"
    assert sonnet.context_window == 1_000_000
