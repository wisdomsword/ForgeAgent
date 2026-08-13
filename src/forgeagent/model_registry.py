"""Model/provider registry: two separate concerns, two separate files.

models.yaml declares what a model CAN DO (capabilities + aliases + wire protocol).
config.yaml declares WHERE requests for it go (provider group -> api_key/base_url).
Each group in config.yaml lists the model_ids it serves; a model_id may only be
listed under one group (enforced at load time), so a model_id routes to exactly one
group's connection info — never a scan across whichever provider's environment
variables happen to be set. See docs/model-client-contract.md's provider-routing
note for the bug this replaced (a request for one vendor's model silently going to a
different vendor's endpoint because that vendor's env var happened to be set too).

Keeping the two files separate means extending routing (add a gateway, add a group)
never requires redeclaring a model's capabilities, and vice versa — a user who wants
to point an existing model at a different gateway edits config.yaml only.

Built-in files live in res/ (shipped with the package, no real keys — only env var
names). A user may extend or override them with ~/.forgeagent/models.yaml and
~/.forgeagent/config.yaml. Both are optional and merged on top of the built-in files
if present. Only the user's config.yaml may set a literal api_key/base_url (never the
built-in file); a literal value takes precedence over its *_env counterpart.
"""

from __future__ import annotations

import os
from importlib import resources
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .models import ModelCapability, PositiveInt
from .sandbox import RestrictedLimits

__all__ = [
    "RegistryError",
    "ModelEntry",
    "GroupConfig",
    "Registry",
    "ResolvedModel",
    "ModelInfo",
    "load_registry",
    "reload_registry",
    "resolve_model",
    "get_capability",
    "list_models",
    "DEFAULT_USER_MODELS_PATH",
    "DEFAULT_USER_CONFIG_PATH",
]

DEFAULT_USER_MODELS_PATH = Path.home() / ".forgeagent" / "models.yaml"
DEFAULT_USER_CONFIG_PATH = Path.home() / ".forgeagent" / "config.yaml"
_SHARED_CONFIG_KEYS = {"context", "groups", "restricted", "search_engine"}


class RegistryError(Exception):
    """Raised for registry problems that should surface at startup: an unknown model
    id, a model listed in more than one group, an alias collision, or a group with no
    way to resolve a key."""


class ModelEntry(BaseModel):
    """One model's capabilities, as declared in models.yaml."""

    client_kind: Literal["anthropic", "openai_compatible"]
    context_window: PositiveInt
    max_output_tokens: PositiveInt
    supports_thinking: bool
    thinking_always_on: bool
    supports_effort: bool
    supports_images: bool = False
    max_tokens_param: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    aliases: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    def to_capability(self, canonical_id: str) -> ModelCapability:
        """Build the capability-gating view of this entry for `canonical_id`.

        Shared by get_capability() and resolve_model() so the two lookup paths can't
        drift apart on which fields they carry over.
        """
        return ModelCapability(
            model_id=canonical_id,
            context_window=self.context_window,
            max_output_tokens=self.max_output_tokens,
            supports_thinking=self.supports_thinking,
            thinking_always_on=self.thinking_always_on,
            supports_effort=self.supports_effort,
            supports_images=self.supports_images,
            client_kind=self.client_kind,
            max_tokens_param=self.max_tokens_param,
        )


class GroupConfig(BaseModel):
    """One provider group, as declared in config.yaml: connection info plus the
    model_ids (from models.yaml) it serves.

    `api_key`/`base_url` are literal values — only ever set via the user's own
    ~/.forgeagent/config.yaml, never the built-in file (enforced by load_registry,
    not by this model, since the same schema is used for both files). When both a
    literal value and its *_env counterpart are usable, the literal value wins.
    """

    api_key_env: str | None = None
    api_key: str | None = None
    base_url_env: str | None = None
    base_url: str | None = None
    models: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class Registry(BaseModel):
    """The merged model capability registry + provider routing table."""

    default_model: str | None = None
    models: dict[str, ModelEntry] = Field(default_factory=dict)
    groups: dict[str, GroupConfig] = Field(default_factory=dict)
    # alias -> canonical model_id, precomputed at load time (validation already walks
    # every alias, so this costs nothing extra) to make _resolve_alias O(1) instead of a
    # linear scan across all models on every lookup. Not read from YAML — built by
    # load_registry after validation.
    alias_index: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class ModelInfo(BaseModel):
    """A human-facing summary of one registered model, for `list_models`."""

    model_id: str
    aliases: list[str]
    client_kind: str
    context_window: int


class ResolvedModel(BaseModel):
    """Everything cli.py needs to build a ModelClient for one model_id."""

    capability: ModelCapability
    api_key: str
    base_url: str | None = None


def _read_yaml(path: Path, *, allowed_keys: set[str], mapping_keys: set[str]) -> dict:
    return _read_yaml_text(
        path.read_text(),
        source=str(path),
        allowed_keys=allowed_keys,
        mapping_keys=mapping_keys,
    )


def _read_builtin_yaml(
    package: str,
    filename: str,
    *,
    allowed_keys: set[str],
    mapping_keys: set[str],
) -> dict:
    text = resources.files(package).joinpath(filename).read_text()
    return _read_yaml_text(
        text,
        source=f"{package}/{filename}",
        allowed_keys=allowed_keys,
        mapping_keys=mapping_keys,
    )


def _read_yaml_text(
    text: str,
    *,
    source: str,
    allowed_keys: set[str],
    mapping_keys: set[str],
) -> dict:
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise RegistryError(f"{source}: invalid configuration") from exc
    if (
        not isinstance(data, dict)
        or set(data).difference(allowed_keys)
        or any(key in data and not isinstance(data[key], dict) for key in mapping_keys)
        or any(
            not isinstance(entry, dict)
            for key in mapping_keys
            for entry in (data.get(key) or {}).values()
        )
    ):
        raise RegistryError(f"{source}: invalid configuration")
    return data


def _merge_models_data(base: dict, override: dict) -> dict:
    merged = dict(base)
    if "default_model" in override:
        merged["default_model"] = override["default_model"]
    models = dict(base.get("models") or {})
    for model_id, entry in (override.get("models") or {}).items():
        if model_id in models:
            merged_entry = dict(models[model_id])
            merged_entry.update(entry)
            models[model_id] = merged_entry
        else:
            models[model_id] = entry
    merged["models"] = models
    return merged


def _merge_config_data(base: dict, override: dict) -> dict:
    groups = dict(base.get("groups") or {})
    for name, group in (override.get("groups") or {}).items():
        if name not in groups:
            groups[name] = group
            continue
        merged_group = dict(groups[name])
        if "models" in group:
            merged_group["models"] = group["models"]
        merged_group.update({k: v for k, v in group.items() if k != "models"})
        groups[name] = merged_group
    merged = {key: value for key, value in base.items() if key != "groups"}
    merged["groups"] = groups
    for key in _SHARED_CONFIG_KEYS - {"groups"}:
        if key in override:
            merged[key] = override[key]
    return merged


def _validate_models_source(data: dict, source: str) -> None:
    """Validate a complete built-in models source before user overlays it."""
    try:
        Registry.model_validate(
            {
                "default_model": data.get("default_model"),
                "models": data.get("models") or {},
                "groups": {},
            }
        )
    except ValidationError as exc:
        raise RegistryError(f"{source}: invalid configuration") from exc


def _validate_config_source(data: dict, source: str) -> None:
    """Validate a complete built-in provider source before user overlays it."""
    try:
        RestrictedLimits.model_validate(data.get("restricted", {}))
        for group in (data.get("groups") or {}).values():
            GroupConfig.model_validate(group)
    except ValidationError as exc:
        raise RegistryError(f"{source}: invalid configuration") from exc


def load_registry(
    *,
    builtin_models_path: Path | None = None,
    builtin_config_path: Path | None = None,
    user_models_path: Path | None = None,
    user_config_path: Path | None = None,
) -> Registry:
    """Load the built-in models.yaml + config.yaml and merge the optional user
    override files on top of each.

    All four paths are injectable for tests; the user paths default to
    ~/.forgeagent/{models,config}.yaml and are silently skipped if absent (override
    files are opt-in, not required).
    """
    models_data = (
        _read_yaml(
            builtin_models_path,
            allowed_keys={"default_model", "models"},
            mapping_keys={"models"},
        )
        if builtin_models_path is not None
        else _read_builtin_yaml(
            "forgeagent.res",
            "models.yaml",
            allowed_keys={"default_model", "models"},
            mapping_keys={"models"},
        )
    )
    models_source = (
        str(builtin_models_path)
        if builtin_models_path is not None
        else "forgeagent.res/models.yaml"
    )
    config_source = (
        str(builtin_config_path)
        if builtin_config_path is not None
        else "forgeagent.res/config.yaml"
    )
    config_data = (
        _read_yaml(
            builtin_config_path,
            allowed_keys=_SHARED_CONFIG_KEYS,
            mapping_keys={"groups"},
        )
        if builtin_config_path is not None
        else _read_builtin_yaml(
            "forgeagent.res",
            "config.yaml",
            allowed_keys=_SHARED_CONFIG_KEYS,
            mapping_keys={"groups"},
        )
    )
    # Built-ins are complete documents. Validate them before an optional user
    # overlay so their own source is retained if they are malformed.
    _validate_models_source(models_data, models_source)
    _validate_config_source(config_data, config_source)

    user_models_path = DEFAULT_USER_MODELS_PATH if user_models_path is None else user_models_path
    if user_models_path.exists():
        models_data = _merge_models_data(
            models_data,
            _read_yaml(
                user_models_path,
                allowed_keys={"default_model", "models"},
                mapping_keys={"models"},
            ),
        )
        models_source = str(user_models_path)

    user_config_path = DEFAULT_USER_CONFIG_PATH if user_config_path is None else user_config_path
    if user_config_path.exists():
        config_data = _merge_config_data(
            config_data,
            _read_yaml(
                user_config_path,
                allowed_keys=_SHARED_CONFIG_KEYS,
                mapping_keys={"groups"},
            ),
        )
        config_source = str(user_config_path)

    try:
        RestrictedLimits.model_validate(config_data.get("restricted", {}))
        registry = Registry.model_validate(
            {
                "default_model": models_data.get("default_model"),
                "models": models_data.get("models") or {},
                "groups": config_data.get("groups") or {},
            }
        )
    except ValidationError as exc:
        raise RegistryError(f"{models_source} or {config_source}: invalid configuration") from exc
    _validate_registry(registry)
    return registry


def reload_registry(
    *,
    builtin_models_path: Path | None = None,
    builtin_config_path: Path | None = None,
    user_models_path: Path | None = None,
    user_config_path: Path | None = None,
) -> Registry:
    """Re-read the YAML files and return a fresh Registry — for a REPL to pick up edits
    to ~/.forgeagent/{models,config}.yaml without a restart. A thin alias of
    load_registry() (which always reads from disk); named separately so the REPL's intent
    ("reload from disk now") is explicit at the call site."""
    return load_registry(
        builtin_models_path=builtin_models_path,
        builtin_config_path=builtin_config_path,
        user_models_path=user_models_path,
        user_config_path=user_config_path,
    )


def _validate_registry(registry: Registry) -> None:
    model_to_group: dict[str, str] = {}
    for group_name, group in registry.groups.items():
        for model_id in group.models:
            if model_id not in registry.models:
                raise RegistryError(
                    f"Group {group_name!r} lists model {model_id!r}, which has no "
                    "capability entry in models.yaml."
                )
            if model_id in model_to_group:
                raise RegistryError(
                    f"Model {model_id!r} is served by both {model_to_group[model_id]!r} "
                    f"and {group_name!r} — a model may only be routed through one group."
                )
            model_to_group[model_id] = group_name

    # Build the alias index while validating (single pass over aliases): a duplicate is a
    # collision error, otherwise it becomes an O(1) alias -> canonical entry for lookups.
    alias_to_model: dict[str, str] = {}
    for model_id, entry in registry.models.items():
        for alias in entry.aliases:
            if alias in registry.models or alias in alias_to_model:
                owner = alias_to_model.get(alias, alias)
                raise RegistryError(f"Alias {alias!r} for {model_id!r} collides with {owner!r}.")
            alias_to_model[alias] = model_id
    registry.alias_index = alias_to_model


def _resolve_alias(model_id: str, registry: Registry) -> str:
    if model_id in registry.models:
        return model_id
    canonical = registry.alias_index.get(model_id)
    if canonical is not None:
        return canonical
    known = ", ".join(sorted(registry.models))
    raise RegistryError(f"Unknown model id {model_id!r}; registered models: {known}")


def list_models(registry: Registry | None = None) -> list[ModelInfo]:
    """Summarise every registered model (id, aliases, client_kind, context window),
    sorted by model_id — for CLI/REPL `models` to answer "what can I use?"."""
    registry = registry or load_registry()
    return [
        ModelInfo(
            model_id=model_id,
            aliases=list(entry.aliases),
            client_kind=entry.client_kind,
            context_window=entry.context_window,
        )
        for model_id, entry in sorted(registry.models.items())
    ]


def _find_group(model_id: str, registry: Registry) -> tuple[str, GroupConfig]:
    for group_name, group in registry.groups.items():
        if model_id in group.models:
            return group_name, group
    raise RegistryError(
        f"Model {model_id!r} has capabilities in models.yaml but is not listed under "
        "any group in config.yaml — add it to a group's `models` list to make it usable."
    )


def get_capability(model_id: str, registry: Registry | None = None) -> ModelCapability:
    """Look up one model's capability only, no api_key/base_url resolution.

    For callers that only need capability-gating (e.g. client-level unit tests
    building a client directly). Uses the built-in registry unless one is supplied.
    """
    registry = registry or load_registry()
    canonical_id = _resolve_alias(model_id, registry)
    return registry.models[canonical_id].to_capability(canonical_id)


def resolve_model(
    model_id: str,
    registry: Registry,
    env: dict[str, str] | None = None,
) -> ResolvedModel:
    """Resolve one model_id (or alias) to its capability + api_key + base_url.

    Routing is by group membership only: model_id determines the group, and only
    that group's own api_key/api_key_env/base_url/base_url_env are ever consulted —
    other groups' environment variables have no effect, even if they happen to be set.
    """
    source = os.environ if env is None else env
    canonical_id = _resolve_alias(model_id, registry)
    entry = registry.models[canonical_id]
    group_name, group = _find_group(canonical_id, registry)

    api_key = group.api_key
    if not api_key and group.api_key_env:
        api_key = source.get(group.api_key_env)
    if not api_key:
        if group.api_key_env:
            how = f"Set the {group.api_key_env!r} environment variable"
        else:
            how = "This group has no api_key_env configured; add a literal api_key"
        raise RegistryError(
            f"Model {canonical_id!r} (group {group_name!r}): no API key available. "
            f"{how}, or add a literal api_key for this group in {DEFAULT_USER_CONFIG_PATH}."
        )

    base_url = group.base_url
    if not base_url and group.base_url_env:
        base_url = source.get(group.base_url_env)

    capability = entry.to_capability(canonical_id)
    return ResolvedModel(capability=capability, api_key=api_key, base_url=base_url or None)
