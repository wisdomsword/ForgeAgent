"""Tests for the MCP manager (M7 Phase 3).

Two layers:
  - config loading is a pure unit test (no servers launched)
  - the multi-server discover / call / isolation tests launch REAL stdio MCP servers
    (tests/mcp_fixture_server.py) against the actual `mcp` SDK, mirroring the Phase-0
    spike's death matrix (docs/m7-tools-mcp-survey.md §八) as committed regression tests.

Each MCPManager test closes its manager in a finally so no background loop/thread leaks.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from forgeagent.mcp_manager import (
    DEFAULT_USER_MCP_PATH,
    MCPManager,
    MCPServerConfig,
    load_mcp_config,
)

_FIXTURE = str(Path(__file__).with_name("mcp_fixture_server.py"))


def _server(
    name: str, mode: str = "normal", pid_file: Path | None = None, **overrides
) -> MCPServerConfig:
    env = {"FORGE_TEST_MCP_NAME": name, "FORGE_TEST_MCP_MODE": mode}
    if pid_file is not None:
        env["FORGE_TEST_MCP_PID_FILE"] = str(pid_file)
    cfg = {
        "command": sys.executable,
        "args": [_FIXTURE],
        "env": env,
    }
    cfg.update(overrides)
    return MCPServerConfig.model_validate(cfg)


# --- config loading (pure unit) ----------------------------------------------


def test_builtin_config_is_empty(tmp_path):
    # A user file that doesn't exist -> only the built-in (empty) servers.
    servers = load_mcp_config(user_path=tmp_path / "absent.yaml")
    assert servers == {}


def test_default_mcp_path_uses_isolated_test_home():
    home = Path.home()
    assert DEFAULT_USER_MCP_PATH == home / ".forgeagent" / "mcp.yaml"
    assert not DEFAULT_USER_MCP_PATH.exists()


def test_user_config_merges_and_parses_aliased_fields(tmp_path):
    builtin = tmp_path / "builtin.yaml"
    builtin.write_text("mcpServers: {}\n")
    user = tmp_path / "user.yaml"
    user.write_text(
        "mcpServers:\n"
        "  fs:\n"
        "    command: mytool\n"
        "    args: ['--root', '/data']\n"
        "    autoApprove: [read_file]\n"
        "    enabled: false\n"
    )
    servers = load_mcp_config(builtin_path=builtin, user_path=user)
    assert set(servers) == {"fs"}
    fs = servers["fs"]
    assert fs.command == "mytool"
    assert fs.auto_approve == ["read_file"]  # aliased from autoApprove
    assert fs.enabled is False


def test_required_defaults_to_false_when_omitted():
    config = MCPServerConfig(command="example-mcp")

    assert config.required is False


def test_user_entry_overrides_builtin_by_name(tmp_path):
    builtin = tmp_path / "builtin.yaml"
    builtin.write_text("mcpServers:\n  fs:\n    command: builtin-cmd\n")
    user = tmp_path / "user.yaml"
    user.write_text("mcpServers:\n  fs:\n    command: user-cmd\n")
    servers = load_mcp_config(builtin_path=builtin, user_path=user)
    assert servers["fs"].command == "user-cmd"


# --- real multi-server integration -------------------------------------------


def test_two_servers_discover_and_route_by_server():
    mgr = MCPManager({"alpha": _server("alpha"), "beta": _server("beta")})
    try:
        mgr.connect()
        status = mgr.server_status()
        assert status["alpha"] == "available"
        assert status["beta"] == "available"
        # Same tool name on both servers, routed by the server field — no collision.
        assert mgr.call_tool("alpha", "echo", {"text": "hi"})["text"] == "alpha: hi"
        assert mgr.call_tool("beta", "echo", {"text": "hi"})["text"] == "beta: hi"
    finally:
        mgr.close()


def test_list_tools_aggregates_across_servers():
    mgr = MCPManager({"alpha": _server("alpha"), "beta": _server("beta")})
    try:
        mgr.connect()
        names = {(t.server, t.name) for t in mgr.list_tools()}
        assert ("alpha", "echo") in names
        assert ("alpha", "add") in names
        assert ("beta", "echo") in names
    finally:
        mgr.close()


def test_expose_allowlist_limits_advertised_tools():
    mgr = MCPManager({"alpha": _server("alpha", expose=["echo"])})
    try:
        mgr.connect()
        names = {t.name for t in mgr.list_tools()}
        assert names == {"echo"}  # 'add' filtered out by expose
    finally:
        mgr.close()


def test_dead_server_isolated_others_available():
    # A server whose command does not exist is marked unavailable; the good one still works.
    dead = MCPServerConfig(command="/nonexistent/forge_test_binary", args=[])
    mgr = MCPManager({"good": _server("good"), "dead": dead})
    try:
        mgr.connect()
        status = mgr.server_status()
        assert status["good"] == "available"
        assert status["dead"].startswith("unavailable")
        assert mgr.call_tool("good", "echo", {"text": "ok"})["text"] == "good: ok"
    finally:
        mgr.close()


def test_call_on_unknown_server_is_structured_error():
    mgr = MCPManager({"alpha": _server("alpha")})
    try:
        mgr.connect()
        result = mgr.call_tool("ghost", "echo", {"text": "x"})
        assert result["ok"] is False
        assert "unknown MCP server" in result["text"]
    finally:
        mgr.close()


def test_mid_call_crash_is_structured_error_not_raise():
    # Server hard-exits during the call -> structured error, no uncaught exception.
    mgr = MCPManager({"crash": _server("crash", mode="crash_on_call")})
    try:
        mgr.connect()
        result = mgr.call_tool("crash", "echo", {"text": "boom"})
        assert result["ok"] is False
        assert "failed" in result["text"].lower()
    finally:
        mgr.close()


def test_disabled_server_not_connected_or_advertised():
    mgr = MCPManager({"off": _server("off", enabled=False)})
    try:
        mgr.connect()
        assert mgr.has_enabled_servers is False
        assert mgr.list_tools() == []
    finally:
        mgr.close()


def test_disabled_required_server_does_not_report_startup_failure():
    mgr = MCPManager({"off": _server("off", enabled=False, required=True)})
    try:
        mgr.connect()

        assert mgr.required_failures() == {}
    finally:
        mgr.close()


def test_optional_unavailable_server_degrades_without_required_failure():
    unavailable = MCPServerConfig(command="/nonexistent/forge_optional_mcp", args=[])
    mgr = MCPManager({"optional": unavailable})
    try:
        mgr.connect()

        assert mgr.server_status()["optional"].startswith("unavailable")
        assert mgr.required_failures() == {}
    finally:
        mgr.close()


def test_tools_prompt_groups_by_server_and_flags_external():
    mgr = MCPManager({"alpha": _server("alpha")})
    try:
        mgr.connect()
        prompt = mgr.tools_prompt()
        assert "## MCP tools" in prompt
        assert "server: alpha" in prompt
        assert "echo" in prompt
        # T8b: the prompt frames MCP tool descriptions as external data, not instructions.
        assert "DATA supplied by those servers" in prompt
    finally:
        mgr.close()


def test_auto_approve_reported_per_server_tool():
    mgr = MCPManager({"alpha": _server("alpha", autoApprove=["echo"])})
    try:
        mgr.connect()
        assert mgr.is_auto_approved("alpha", "echo") is True
        assert mgr.is_auto_approved("alpha", "add") is False
    finally:
        mgr.close()


# --- Phase-6 review fixes (regression guards) --------------------------------


def test_close_terminates_child_processes_no_leak(tmp_path):
    # Review finding #1: close() must await holders (so each async-with __aexit__ runs
    # and terminates the child) before stopping the loop — else children leak.
    pid_file = tmp_path / "alpha.pid"
    mgr = MCPManager({"alpha": _server("alpha", pid_file=pid_file)})
    try:
        mgr.connect()
        pid = int(pid_file.read_text(encoding="utf-8"))
        os.kill(pid, 0)
    finally:
        mgr.close()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"fixture process {pid} survived MCPManager.close()")


def test_enable_startup_disabled_server_connects_it():
    # Review finding #2: enable() on a server disabled at load must actually start a
    # holder and make it available (not just flip a flag with no effect).
    mgr = MCPManager({"on": _server("on"), "off": _server("off", enabled=False)})
    try:
        mgr.connect()
        assert mgr.server_status()["off"] == "unavailable"
        assert mgr.enable("off") is True
        assert mgr.server_status()["off"] == "available"
        assert mgr.call_tool("off", "echo", {"text": "hi"})["text"] == "off: hi"
    finally:
        mgr.close()


def test_disable_stops_holder_and_drops_from_catalog():
    mgr = MCPManager({"alpha": _server("alpha"), "beta": _server("beta")})
    try:
        mgr.connect()
        assert mgr.disable("beta") is True
        names = {t.server for t in mgr.list_tools()}
        assert "beta" not in names  # dropped from catalog
        assert mgr.server_status()["beta"] == "unavailable: disabled"
        assert mgr.call_tool("alpha", "echo", {"text": "x"})["text"] == "alpha: x"  # others live
    finally:
        mgr.close()


def test_mid_call_crash_marks_server_unavailable():
    # Review finding #5: after a call crashes the server, it must be marked unavailable
    # (dropped from the catalog) so later rounds don't keep hitting a dead process.
    mgr = MCPManager({"crash": _server("crash", mode="crash_on_call")})
    try:
        mgr.connect()
        assert mgr.server_status()["crash"] == "available"  # healthy until first call
        result = mgr.call_tool("crash", "echo", {"text": "boom"})
        assert result["ok"] is False
        assert mgr.server_status()["crash"].startswith("unavailable")
        assert mgr.list_tools() == []  # no longer advertised
    finally:
        mgr.close()


def test_mcp_result_secret_values_are_masked():
    # Review finding #3: MCP result content is external data and must be secret-masked
    # like executor output. Feed a fake secret env value back through echo and assert it's
    # redacted (not surfaced verbatim into the feedback loop).
    import os

    os.environ["FORGE_TEST_FAKE_TOKEN"] = "supersecretvalue123"
    try:
        mgr = MCPManager({"alpha": _server("alpha")})
        try:
            mgr.connect()
            out = mgr.call_tool("alpha", "echo", {"text": "supersecretvalue123"})
            assert "supersecretvalue123" not in out["text"]
            assert "REDACTED" in out["text"]
        finally:
            mgr.close()
    finally:
        del os.environ["FORGE_TEST_FAKE_TOKEN"]


@pytest.mark.skip(reason="hang test is slow; covered by the Phase-0 spike (§八 D4)")
def test_hung_call_times_out():  # pragma: no cover - documented, exercised in spike
    ...
