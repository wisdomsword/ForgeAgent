"""A tiny stdio MCP server used as a test fixture (M7 Phase 3).

Not shipped with the package — it lives under tests/ purely so the MCPManager tests can
launch a real stdio MCP server and exercise the full discover -> call -> feedback path
against the actual `mcp` SDK (not a mock of it).

Behaviour is selected by env vars so one script can play the servers the tests need:
  FORGE_TEST_MCP_NAME   the server's identity, echoed into tool output (default "fixture")
  FORGE_TEST_MCP_MODE   normal        -> working echo + add tools
                        crash_on_call -> the tool hard-exits mid-call (isolation test)
                        hang_on_call  -> the echo call never returns (timeout test)
                        startup_chatter -> writes synthetic stderr, then starts normally
                        docker_failure  -> writes synthetic Docker stderr, then exits
"""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

NAME = os.environ.get("FORGE_TEST_MCP_NAME", "fixture")
MODE = os.environ.get("FORGE_TEST_MCP_MODE", "normal")

if MODE == "startup_chatter":
    print("synthetic MCP startup chatter", file=sys.stderr, flush=True)
elif MODE == "docker_failure":
    print(
        "Cannot connect to the Docker daemon at unix:///synthetic/docker.sock. "
        "Is the docker daemon running?",
        file=sys.stderr,
        flush=True,
    )
    raise SystemExit(1)

if MODE == "ignore_shutdown":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

pid_file = os.environ.get("FORGE_TEST_MCP_PID_FILE")
if pid_file:
    Path(pid_file).write_text(str(os.getpid()), encoding="utf-8")

server = FastMCP(NAME)


@server.tool()
def echo(text: str) -> str:
    """Echo the given text, prefixed with this server's name."""
    if MODE == "crash_on_call":
        os._exit(9)
    if MODE == "hang_on_call":
        while True:
            time.sleep(1)
    return f"{NAME}: {text}"


@server.tool()
def add(a: int, b: int) -> int:
    """Add two integers and return the sum."""
    return a + b


if __name__ == "__main__":
    server.run()
    if MODE == "ignore_shutdown":
        while True:
            time.sleep(1)
