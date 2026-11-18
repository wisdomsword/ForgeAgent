"""Verify the SDK keeps MCP tool output validation within its schema registry."""

import asyncio
from types import SimpleNamespace

import jsonschema
import pytest
from mcp import ClientSession, types
from referencing.exceptions import NoSuchResource


def test_sdk_validates_local_references_with_an_explicit_registry(monkeypatch):
    original = jsonschema.validate
    registries = []

    def observe_validation(instance, schema, **options):
        registries.append(options.get("registry"))
        return original(instance, schema, **options)

    monkeypatch.setattr(jsonschema, "validate", observe_validation)
    session = SimpleNamespace(
        _tool_output_schemas={
            "fixture": {"$defs": {"response": {"type": "object"}}, "$ref": "#/$defs/response"}
        }
    )
    result = types.CallToolResult(content=[], structuredContent={"fixture": "ok"})

    asyncio.run(ClientSession._validate_tool_result(session, "fixture", result))

    assert len(registries) == 1
    assert registries[0] is not None
    with pytest.raises(NoSuchResource):
        registries[0].get_or_retrieve("urn:forgeagent:test:missing-schema")
