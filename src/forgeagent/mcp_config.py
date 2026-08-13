"""Strict loading and schema validation for MCP server configuration."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from .model_registry import RegistryError

DEFAULT_USER_MCP_PATH = Path.home() / ".forgeagent" / "mcp.yaml"


class MCPServerConfig(BaseModel):
    """One MCP server entry in the Claude Desktop compatible mcpServers shape."""

    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: StrictBool = True
    required: StrictBool = False
    auto_approve: list[str] = Field(default_factory=list, alias="autoApprove")
    expose: list[str] | None = None

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


def load_mcp_config(
    *,
    builtin_path: Path | None = None,
    user_path: Path | None = None,
) -> dict[str, MCPServerConfig]:
    """Load built-in MCP servers, then replace matching entries from the user file."""
    if builtin_path is not None:
        builtin_data = _read_mcp_yaml(builtin_path.read_text(), source=str(builtin_path))
        builtin_source = str(builtin_path)
    else:
        from importlib import resources

        text = resources.files("forgeagent.res").joinpath("mcp.yaml").read_text()
        builtin_data = _read_mcp_yaml(text, source="forgeagent.res/mcp.yaml")
        builtin_source = "forgeagent.res/mcp.yaml"
    servers = _validate_mcp_servers(builtin_data, source=builtin_source)

    resolved_user_path = DEFAULT_USER_MCP_PATH if user_path is None else user_path
    if resolved_user_path.exists():
        user_data = _read_mcp_yaml(resolved_user_path.read_text(), source=str(resolved_user_path))
        servers.update(_validate_mcp_servers(user_data, source=str(resolved_user_path)))
    return servers


def _read_mcp_yaml(text: str, *, source: str) -> dict:
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise RegistryError(f"{source}: invalid configuration") from exc
    if (
        not isinstance(data, dict)
        or set(data).difference({"mcpServers"})
        or not isinstance(data.get("mcpServers", {}), dict)
    ):
        raise RegistryError(f"{source}: invalid configuration")
    return data


def _validate_mcp_servers(data: dict, *, source: str) -> dict[str, MCPServerConfig]:
    try:
        return {
            name: MCPServerConfig.model_validate(entry)
            for name, entry in (data.get("mcpServers") or {}).items()
        }
    except ValidationError as exc:
        raise RegistryError(f"{source}: invalid configuration") from exc
