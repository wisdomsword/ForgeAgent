"""A tiny stdio MCP server used as a test fixture (M7 Phase 3).

Not shipped with the package — it lives under tests/ purely so the MCPManager tests can
launch a real stdio MCP server and exercise the full discover -> call -> feedback path
against the actual `mcp` SDK (not a mock of it).

Behaviour is selected by env vars so one script can play the servers the tests need:
  FORGE_TEST_MCP_NAME   the server's identity, echoed into tool output (default "fixture")
  FORGE_TEST_MCP_MODE   normal        -> working echo + add tools
                        crash_on_call -> the tool hard-exits mid-call (isolation test)
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

NAME = os.environ.get("FORGE_TEST_MCP_NAME", "fixture")
MODE = os.environ.get("FORGE_TEST_MCP_MODE", "normal")

server = FastMCP(NAME)


@server.tool()
def echo(text: str) -> str:
    """Echo the given text, prefixed with this server's name."""
    if MODE == "crash_on_call":
        os._exit(9)
    return f"{NAME}: {text}"


@server.tool()
def add(a: int, b: int) -> int:
    """Add two integers and return the sum."""
    return a + b


if __name__ == "__main__":
    server.run()
