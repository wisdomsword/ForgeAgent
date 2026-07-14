"""Tests for the MCP manager (M7 Phase 3).

Two layers:
  - config loading is a pure unit test (no servers launched)
  - the multi-server discover / call / isolation tests launch REAL stdio MCP servers
    (tests/mcp_fixture_server.py) against the actual `mcp` SDK, mirroring the Phase-0
    spike's death matrix (docs/m7-tools-mcp-survey.md §八) as committed regression tests.

Each MCPManager test closes its manager in a finally so no background loop/thread leaks.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import gc
import logging
import os
import sys
import threading
import time
import warnings
from pathlib import Path

import pytest

import forgeagent.mcp_manager as mcp_manager_module
from forgeagent.mcp_manager import (
    DEFAULT_USER_MCP_PATH,
    MCPManager,
    MCPServerConfig,
    load_mcp_config,
)
from forgeagent.secret_policy import REDACTED

_FIXTURE = str(Path(__file__).with_name("mcp_fixture_server.py"))


class _FutureProbe:
    def __init__(
        self,
        *,
        result: set[str] | None = None,
        error: BaseException | None = None,
        wait_for_timeout: bool = False,
    ):
        self._result = set() if result is None else result
        self._error = error
        self._wait_for_timeout = wait_for_timeout
        self.result_timeouts: list[float] = []
        self.cancel_calls = 0

    def result(self, timeout: float) -> set[str]:
        self.result_timeouts.append(timeout)
        if self._wait_for_timeout:
            time.sleep(timeout)
            raise concurrent.futures.TimeoutError
        if self._error is not None:
            raise self._error
        return self._result

    def cancel(self) -> bool:
        self.cancel_calls += 1
        return True


class _LoopProbe:
    def __init__(
        self,
        *,
        stop_error: Exception | None = None,
        close_error: Exception | None = None,
    ):
        self._stop_error = stop_error
        self._close_error = close_error
        self.stop_calls = 0
        self.close_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1

    def call_soon_threadsafe(self, callback) -> None:
        if self._stop_error is not None:
            raise self._stop_error
        callback()

    def close(self) -> None:
        self.close_calls += 1
        if self._close_error is not None:
            raise self._close_error


class _ThreadProbe:
    name = "forgeagent-mcp-loop"
    ident = 31415

    def __init__(
        self,
        *,
        alive: bool,
        alive_results: list[bool] | None = None,
        wait_for_timeout: bool = False,
        join_error: Exception | None = None,
    ):
        self.alive = alive
        self._alive_results = iter(alive_results or [])
        self._wait_for_timeout = wait_for_timeout
        self._join_error = join_error
        self.join_timeouts: list[float] = []

    def join(self, timeout: float) -> None:
        self.join_timeouts.append(timeout)
        if self._wait_for_timeout and self.alive:
            time.sleep(timeout)
        if self._join_error is not None:
            raise self._join_error

    def is_alive(self) -> bool:
        self.alive = next(self._alive_results, self.alive)
        return self.alive


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


def test_required_failures_mask_secret_bearing_status(monkeypatch):
    secret = "mcp-required-secret-value"
    monkeypatch.setattr("forgeagent.mcp_manager.sensitive_env_values", lambda: {secret})
    mgr = MCPManager({"required": MCPServerConfig(command="unused", args=[], required=True)})
    mgr._states["required"].status = f"unavailable: RuntimeError: {secret}"

    assert mgr.required_failures() == {"required": f"unavailable: RuntimeError: {REDACTED}"}


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


def test_close_stops_normal_and_cancel_only_holders_on_loop_thread():
    mgr = MCPManager(
        {
            "normal": MCPServerConfig(command="unused"),
            "cancel-only": MCPServerConfig(command="unused"),
        },
        shutdown_timeout=0.04,
        thread_join_timeout=0.02,
    )
    loop = asyncio.new_event_loop()
    thread = threading.Thread(
        target=loop.run_forever,
        name="forgeagent-mcp-loop",
        daemon=True,
    )
    mgr._loop = loop
    mgr._thread = thread
    cancelled = threading.Event()
    outcomes: list[tuple[str, int]] = []
    thread.start()

    async def install_holders() -> None:
        normal_stop = asyncio.Event()
        cancel_only_stop = asyncio.Event()
        mgr._states["normal"].stop = normal_stop
        mgr._states["cancel-only"].stop = cancel_only_stop
        mgr._sessions.update({"normal": object(), "cancel-only": object()})

        async def normal_holder() -> None:
            try:
                await normal_stop.wait()
            except asyncio.CancelledError:
                outcomes.append(("normal-cancelled", threading.get_ident()))
                raise
            else:
                outcomes.append(("normal-stopped", threading.get_ident()))
            finally:
                outcomes.append(("normal-cleanup", threading.get_ident()))
                mgr._sessions.pop("normal", None)

        async def cancel_only_holder() -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                outcomes.append(("cancel-only-cancelled", threading.get_ident()))
                raise
            finally:
                outcomes.append(("cancel-only-cleanup", threading.get_ident()))
                mgr._sessions.pop("cancel-only", None)

        mgr._holders["normal"] = asyncio.create_task(normal_holder())
        mgr._holders["cancel-only"] = asyncio.create_task(cancel_only_holder())

    asyncio.run_coroutine_threadsafe(install_holders(), loop).result(timeout=1)
    started = time.monotonic()
    try:
        assert mgr.close() is None
    finally:
        if thread.is_alive():

            async def cancel_test_holders() -> None:
                holders = list(mgr._holders.values())
                for holder in holders:
                    holder.cancel()
                await asyncio.gather(*holders, return_exceptions=True)

            asyncio.run_coroutine_threadsafe(cancel_test_holders(), loop).result(timeout=1)
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=1)
        if not thread.is_alive() and not loop.is_closed():
            loop.close()

    elapsed = time.monotonic() - started
    assert elapsed < 0.56
    assert mgr._closed is True
    assert cancelled.is_set()
    assert outcomes == [
        ("normal-stopped", thread.ident),
        ("normal-cleanup", thread.ident),
        ("cancel-only-cancelled", thread.ident),
        ("cancel-only-cleanup", thread.ident),
    ]
    assert mgr._shutdown_future is None
    assert mgr._holders == {}
    assert mgr._sessions == {}
    assert mgr._loop is None
    assert mgr._thread is None


def test_close_blocked_loop_drains_cancellation_before_stop_and_retry(monkeypatch, caplog):
    secret = "shutdown-secret-content"
    mgr = MCPManager(
        {
            "pending": MCPServerConfig(
                command="/secret/server/path",
                args=["--secret-argument"],
                env={"TOKEN": "secret-env-value"},
            )
        },
        shutdown_timeout=0.03,
        thread_join_timeout=0.02,
    )
    loop = asyncio.new_event_loop()
    thread = threading.Thread(
        target=loop.run_forever,
        name="forgeagent-mcp-loop",
        daemon=True,
    )
    session = object()
    blocked = threading.Event()
    release = threading.Event()
    cancellation_cleanup = threading.Event()
    cleanup_thread_ids: list[int] = []
    submissions = 0
    mgr._loop = loop
    mgr._thread = thread
    mgr._states["pending"].status = f"available: {secret}"
    thread.start()

    async def install_holder() -> None:
        mgr._states["pending"].stop = asyncio.Event()
        mgr._sessions["pending"] = session

        async def holder() -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellation_cleanup.set()
                raise
            finally:
                cleanup_thread_ids.append(threading.get_ident())
                mgr._sessions.pop("pending", None)

        mgr._holders["pending"] = asyncio.create_task(holder())

    original_submit = asyncio.run_coroutine_threadsafe
    original_submit(install_holder(), loop).result(timeout=1)
    holder = mgr._holders["pending"]

    def block_loop_thread() -> None:
        blocked.set()
        release.wait(timeout=1)

    loop.call_soon_threadsafe(block_loop_thread)
    assert blocked.wait(timeout=1)

    def submit(coro, submitted_loop):
        nonlocal submissions
        submissions += 1
        assert submitted_loop is loop
        return original_submit(coro, submitted_loop)

    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", submit)
    caplog.set_level(logging.WARNING, logger="forgeagent.mcp_manager")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        started = time.monotonic()
        try:
            assert mgr.close() is None
            first_elapsed = time.monotonic() - started

            assert first_elapsed < 0.55
            assert mgr._closed is True
            assert submissions == 1
            future = mgr._shutdown_future
            assert future is not None
            assert future.cancelled()
            assert mgr._holders == {"pending": holder}
            assert mgr._sessions == {"pending": session}
            assert mgr._loop is loop
            assert mgr._thread is thread
            warning = caplog.text
            assert "forgeagent-mcp-loop" in warning
            assert f"ident={thread.ident}" in warning
            assert "alive=True" in warning
            assert "pending=['pending']" in warning
            assert "timeout=" in warning
            assert "shutdown incomplete; resources may remain" in warning
            assert secret not in warning
            assert "/secret/server/path" not in warning
            assert "--secret-argument" not in warning
            assert "secret-env-value" not in warning

            release.set()
            thread.join(timeout=1)
            assert cancellation_cleanup.wait(timeout=0.5)
            assert cleanup_thread_ids == [thread.ident]
            assert not thread.is_alive()
            assert mgr._holders == {}
            assert mgr._sessions == {}

            caplog.clear()
            assert mgr.close() is None

            assert submissions == 1
            assert "shutdown incomplete" not in caplog.text
            assert mgr._shutdown_future is None
            assert mgr._holders == {}
            assert mgr._sessions == {}
            assert mgr._loop is None
            assert mgr._thread is None
            gc.collect()
            assert "Task was destroyed but it is pending" not in caplog.text
            assert not any("never awaited" in str(item.message) for item in caught)
        finally:
            release.set()
            if thread.is_alive():
                loop.call_soon_threadsafe(loop.stop)
                thread.join(timeout=1)
            if not loop.is_closed():
                loop.close()


def test_repeated_close_recreates_join_deadline_from_current_clock(monkeypatch):
    mgr = MCPManager({}, shutdown_timeout=0.03, thread_join_timeout=0.02)
    mgr._closed = True
    mgr._loop = _LoopProbe()
    mgr._thread = _ThreadProbe(alive=True)
    mgr._shutdown_future = _FutureProbe()
    deadlines: list[tuple[float, frozenset[str]]] = []
    clock = iter([100.0, 250.0])

    monkeypatch.setattr(mcp_manager_module.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(
        mgr,
        "_stop_and_join",
        lambda deadline, pending: deadlines.append((deadline, pending)),
    )

    mgr.close()
    mgr.close()

    assert deadlines == [(100.02, frozenset()), (250.02, frozenset())]
    assert mgr._shutdown_future.cancel_calls == 2


@pytest.mark.parametrize(
    "error",
    [RuntimeError("thread start"), KeyboardInterrupt(), SystemExit(7)],
)
def test_connect_start_failure_cleans_unpublished_loop_and_preserves_error(monkeypatch, error):
    mgr = MCPManager({"pending": MCPServerConfig(command="unused")})
    loop = asyncio.new_event_loop()
    monkeypatch.setattr(mcp_manager_module.asyncio, "new_event_loop", lambda: loop)

    def fail_start(self) -> None:
        raise error

    monkeypatch.setattr(mcp_manager_module.threading.Thread, "start", fail_start)

    try:
        with pytest.raises(type(error)):
            mgr.connect()

        assert mgr._started is False
        assert mgr._loop is None
        assert mgr._thread is None
        assert loop.is_closed()
    finally:
        if not loop.is_closed():
            loop.close()


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(7)])
def test_connect_partial_start_interrupt_stops_worker_and_closes_loop(monkeypatch, error):
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        thread_join_timeout=0.2,
    )
    loop = asyncio.new_event_loop()
    started_threads: list[threading.Thread] = []
    original_start = threading.Thread.start
    monkeypatch.setattr(mcp_manager_module.asyncio, "new_event_loop", lambda: loop)

    def start_then_interrupt(thread) -> None:
        original_start(thread)
        started_threads.append(thread)
        deadline = time.monotonic() + 0.05
        while not loop.is_running() and time.monotonic() < deadline:
            time.sleep(0.001)
        raise error

    monkeypatch.setattr(mcp_manager_module.threading.Thread, "start", start_then_interrupt)

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with pytest.raises(type(error)) as raised:
                mgr.connect()
            error.__traceback__ = None
            gc.collect()

        worker = started_threads[0]
        assert raised.value is error
        assert mgr._started is False
        assert mgr._loop is None
        assert mgr._thread is None
        assert not worker.is_alive()
        assert loop.is_closed()
        assert not any(isinstance(item.message, RuntimeWarning) for item in caught)
    finally:
        if started_threads and started_threads[0].is_alive():
            loop.call_soon_threadsafe(loop.stop)
            started_threads[0].join(timeout=1)
        if not loop.is_closed():
            loop.close()


@pytest.mark.parametrize(
    "error",
    [RuntimeError("submission"), KeyboardInterrupt(), SystemExit(7)],
)
def test_close_submission_rejection_closes_coroutine_and_preserves_error(monkeypatch, error):
    mgr = MCPManager({}, shutdown_timeout=0.03, thread_join_timeout=0.02)
    mgr._loop = _LoopProbe()
    mgr._thread = _ThreadProbe(alive=True, alive_results=[True, False])
    submitted = []

    def reject(coro, submitted_loop):
        submitted.append(coro)
        assert submitted_loop is mgr._loop
        raise error

    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", reject)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if isinstance(error, Exception):
            assert mgr.close() is None
        else:
            with pytest.raises(type(error)):
                mgr.close()
        shutdown_coro = submitted[0]
        try:
            assert shutdown_coro.cr_frame is None
        finally:
            shutdown_coro.close()
        submitted.clear()
        error.__traceback__ = None
        gc.collect()

    assert not any("never awaited" in str(item.message) for item in caught)


def test_close_on_already_closed_loop_has_no_unawaited_coroutine_warning():
    mgr = MCPManager({}, shutdown_timeout=0.03, thread_join_timeout=0.02)
    loop = asyncio.new_event_loop()
    loop.close()
    mgr._loop = loop
    mgr._thread = _ThreadProbe(alive=False)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert mgr.close() is None
        gc.collect()

    assert mgr._loop is None
    assert mgr._thread is None
    assert not any("never awaited" in str(item.message) for item in caught)


def test_close_on_stopped_loop_without_holders_does_not_queue_coroutine():
    mgr = MCPManager({}, shutdown_timeout=0.03, thread_join_timeout=0.02)
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    mgr._loop = loop
    mgr._thread = thread
    thread.start()
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=1)
    assert not thread.is_alive()

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert mgr.close() is None
            gc.collect()

        assert loop.is_closed()
        assert mgr._shutdown_future is None
        assert mgr._loop is None
        assert mgr._thread is None
        assert not any("never awaited" in str(item.message) for item in caught)
    finally:
        if not loop.is_closed():
            recovery = threading.Thread(target=loop.run_forever, daemon=True)
            recovery.start()
            recovery.join(timeout=1)
            if recovery.is_alive():
                loop.call_soon_threadsafe(loop.stop)
                recovery.join(timeout=1)
            loop.close()


def test_close_dead_thread_retains_incomplete_resources_without_submission(monkeypatch, caplog):
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        shutdown_timeout=0.03,
        thread_join_timeout=0.02,
    )
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    holder = object()
    session = object()
    submissions = 0
    mgr._loop = loop
    mgr._thread = thread
    mgr._holders["pending"] = holder
    mgr._sessions["pending"] = session

    def reject_submission(coro, submitted_loop):
        nonlocal submissions
        submissions += 1
        assert submitted_loop is loop
        coro.close()
        raise RuntimeError("stopped loop must not receive shutdown work")

    monkeypatch.setattr(
        mcp_manager_module.asyncio,
        "run_coroutine_threadsafe",
        reject_submission,
    )
    caplog.set_level(logging.WARNING, logger="forgeagent.mcp_manager")

    try:
        assert mgr.close() is None

        assert submissions == 0
        assert mgr._shutdown_future is None
        assert mgr._holders == {"pending": holder}
        assert mgr._sessions == {"pending": session}
        assert mgr._loop is loop
        assert mgr._thread is thread
        assert "alive=False" in caplog.text
        assert "pending=['pending']" in caplog.text
        assert "shutdown incomplete; resources may remain" in caplog.text
    finally:
        mgr._holders.clear()
        mgr._sessions.clear()
        loop.close()


def test_close_internal_failure_keeps_finalization_best_effort(monkeypatch, caplog):
    secret = "internal-shutdown-secret"
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        shutdown_timeout=0.03,
        thread_join_timeout=0.02,
    )
    loop = _LoopProbe(
        stop_error=RuntimeError(f"stop {secret}"),
        close_error=OSError(f"close {secret}"),
    )
    thread = _ThreadProbe(
        alive=True,
        alive_results=[True, False],
        join_error=RuntimeError(f"join {secret}"),
    )
    future = _FutureProbe(error=RuntimeError(f"future {secret}"))
    mgr._loop = loop
    mgr._thread = thread
    mgr._holders["pending"] = object()
    mgr._sessions["pending"] = object()
    mgr._shutdown_complete.set()

    def submit(coro, submitted_loop):
        assert submitted_loop is loop
        coro.close()
        return future

    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", submit)
    caplog.set_level(logging.WARNING, logger="forgeagent.mcp_manager")

    assert mgr.close() is None

    assert mgr._closed is True
    assert future.cancel_calls == 1
    assert len(thread.join_timeouts) == 1
    assert loop.close_calls == 1
    assert mgr._shutdown_future is None
    assert mgr._holders == {}
    assert mgr._sessions == {}
    assert mgr._loop is None
    assert mgr._thread is None
    assert "MCP shutdown failed: RuntimeError" in caplog.text
    assert "MCP loop stop failed: RuntimeError" in caplog.text
    assert "MCP loop thread join failed: RuntimeError" in caplog.text
    assert "MCP loop close failed: OSError" in caplog.text
    assert secret not in caplog.text


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt(), SystemExit(7)])
def test_close_preserves_process_control_exceptions(monkeypatch, interrupt):
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        shutdown_timeout=0.03,
        thread_join_timeout=0.02,
    )
    loop = _LoopProbe()
    thread = _ThreadProbe(alive=True, alive_results=[True, False])
    future = _FutureProbe(error=interrupt)
    mgr._loop = loop
    mgr._thread = thread
    mgr._shutdown_complete.set()

    def submit(coro, submitted_loop):
        assert submitted_loop is loop
        coro.close()
        return future

    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", submit)

    with pytest.raises(type(interrupt)):
        mgr.close()

    assert mgr._closed is True
    assert loop.stop_calls == 1
    assert len(thread.join_timeouts) == 1
    assert loop.close_calls == 1
    assert mgr._loop is None
    assert mgr._thread is None


def test_close_without_loop_is_idempotent_and_clears_empty_resources():
    mgr = MCPManager({}, shutdown_timeout=0.03, thread_join_timeout=0.02)

    assert mgr.close() is None
    assert mgr.close() is None

    assert mgr._closed is True
    assert mgr._shutdown_future is None
    assert mgr._holders == {}
    assert mgr._sessions == {}
    assert mgr._loop is None
    assert mgr._thread is None


@pytest.mark.parametrize("mode", ["normal", "ignore_shutdown"])
def test_close_terminates_child_processes_no_leak(tmp_path, monkeypatch, mode):
    # Review finding #1: close() must await holders (so each async-with __aexit__ runs
    # and terminates the child) before stopping the loop — else children leak.
    import mcp.client.stdio as mcp_stdio

    original_terminate = mcp_stdio._terminate_process_tree

    async def terminate_quickly(process) -> None:
        await original_terminate(process, timeout_seconds=0.05)

    monkeypatch.setattr(mcp_stdio, "PROCESS_TERMINATION_TIMEOUT", 0.05)
    monkeypatch.setattr(mcp_stdio, "_terminate_process_tree", terminate_quickly)
    pid_file = tmp_path / f"{mode}.pid"
    mgr = MCPManager({"alpha": _server("alpha", mode=mode, pid_file=pid_file)})
    try:
        mgr.connect()
        assert mgr._thread is not None
        assert mgr._thread.name == "forgeagent-mcp-loop"
        pid = int(pid_file.read_text(encoding="utf-8"))
        os.kill(pid, 0)
    finally:
        started = time.monotonic()
        mgr.close()
        elapsed = time.monotonic() - started
    assert elapsed < mgr._shutdown_timeout + mgr._thread_join_timeout + 0.5
    assert mgr._closed is True
    assert mgr._shutdown_future is None
    assert mgr._holders == {}
    assert mgr._sessions == {}
    assert mgr._loop is None
    assert mgr._thread is None

    deadline = time.monotonic() + 0.5
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


def test_disable_timeout_keeps_holder_visible_until_overlapping_close_finishes_cleanup():
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        connect_timeout=-4.98,
        shutdown_timeout=0.03,
        thread_join_timeout=0.02,
    )
    loop = asyncio.new_event_loop()
    thread = threading.Thread(
        target=loop.run_forever,
        name="forgeagent-mcp-loop",
        daemon=True,
    )
    cleanup_started = threading.Event()
    cleanup_cancelled = threading.Event()
    cleanup_finished = threading.Event()
    loop_state: dict[str, asyncio.Event] = {}
    mgr._loop = loop
    mgr._thread = thread
    thread.start()

    async def install_holder() -> None:
        stop = asyncio.Event()
        cleanup_release = asyncio.Event()
        loop_state["cleanup_release"] = cleanup_release
        mgr._states["pending"].stop = stop
        mgr._sessions["pending"] = object()

        async def holder() -> None:
            try:
                await stop.wait()
            finally:
                cleanup_started.set()
                while not cleanup_release.is_set():
                    try:
                        await cleanup_release.wait()
                    except asyncio.CancelledError:
                        cleanup_cancelled.set()
                mgr._sessions.pop("pending", None)
                cleanup_finished.set()

        mgr._holders["pending"] = asyncio.create_task(holder())
        await asyncio.sleep(0)

    asyncio.run_coroutine_threadsafe(install_holder(), loop).result(timeout=1)
    holder = mgr._holders["pending"]

    try:
        with pytest.raises(concurrent.futures.TimeoutError):
            mgr.disable("pending")
        assert cleanup_started.wait(timeout=1)
        assert mgr._holders.get("pending") is holder

        started = time.monotonic()
        assert mgr.close() is None
        assert time.monotonic() - started < 0.55
        assert cleanup_cancelled.wait(timeout=1)
        assert not cleanup_finished.is_set()
        assert mgr._holders.get("pending") is holder
        assert mgr._loop is loop
        assert mgr._thread is thread

        loop.call_soon_threadsafe(loop_state["cleanup_release"].set)
        assert cleanup_finished.wait(timeout=1)
        thread.join(timeout=1)
        assert not thread.is_alive()

        assert mgr.close() is None
        assert mgr._shutdown_future is None
        assert mgr._holders == {}
        assert mgr._sessions == {}
        assert mgr._loop is None
        assert mgr._thread is None
    finally:
        if thread.is_alive():
            loop.call_soon_threadsafe(loop_state["cleanup_release"].set)
            cleanup_finished.wait(timeout=1)
        if thread.is_alive():
            asyncio.run_coroutine_threadsafe(asyncio.sleep(0), loop).result(timeout=1)
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=1)
        if not loop.is_closed():
            loop.close()


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
