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
    MCPToolInfo,
    load_mcp_config,
)

_FIXTURE = str(Path(__file__).with_name("mcp_fixture_server.py"))


class _FutureProbe:
    def __init__(
        self,
        *,
        result: set[str] | None = None,
        error: BaseException | None = None,
        cancel_error: BaseException | None = None,
        wait_for_timeout: bool = False,
    ):
        self._result = set() if result is None else result
        self._error = error
        self._cancel_error = cancel_error
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
        if self._cancel_error is not None:
            raise self._cancel_error
        return True


class _CloseProbe:
    def __init__(self, error: BaseException | None = None):
        self._error = error
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        if self._error is not None:
            raise self._error


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


class _TextContent:
    type = "text"

    def __init__(self, text: str):
        self.text = text


class _CallResult:
    isError = False

    def __init__(self, text: str):
        self.content = [_TextContent(text)]


class _SessionProbe:
    def __init__(self, text: str, *, error: BaseException | None = None, before_error=None):
        self.text = text
        self.error = error
        self.before_error = before_error
        self.call_count = 0
        self.thread_ids: list[int] = []
        self.read_timeouts = []

    def call_tool(self, tool: str, arguments: dict, *, read_timeout_seconds):
        self.call_count += 1
        self.thread_ids.append(threading.get_ident())
        self.read_timeouts.append(read_timeout_seconds)

        async def run():
            if self.before_error is not None:
                self.before_error()
            if self.error is not None:
                raise self.error
            return _CallResult(self.text)

        return run()


def _tool(server: str = "pending") -> MCPToolInfo:
    return MCPToolInfo(server=server, name="echo", description="Echo")


async def _park_until(stop: asyncio.Event) -> None:
    await stop.wait()


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

    assert mgr.required_failures() == {"required": "unavailable: RuntimeError"}


@pytest.mark.parametrize(
    "error",
    [concurrent.futures.TimeoutError(), KeyboardInterrupt(), SystemExit(7)],
)
def test_submit_failure_cancels_only_the_concurrent_waiter(monkeypatch, error):
    mgr = MCPManager({})
    mgr._loop = object()
    future = _FutureProbe(error=error)

    def submit(coro, loop):
        coro.close()
        return future

    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", submit)

    with pytest.raises(type(error)) as raised:
        mgr._submit(asyncio.sleep(0), timeout=0.01)

    assert raised.value is error
    assert future.cancel_calls == 1
    error.__traceback__ = None


def test_submit_preserves_primary_when_rejected_coroutine_close_raises(monkeypatch):
    mgr = MCPManager({})
    mgr._loop = object()
    primary = KeyboardInterrupt()

    class CloseFailureCoroutine:
        def close(self):
            raise asyncio.CancelledError

    def reject(coro, loop):
        raise primary

    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", reject)

    with pytest.raises(KeyboardInterrupt) as raised:
        mgr._submit(CloseFailureCoroutine(), timeout=0.01)

    assert raised.value is primary
    primary.__traceback__ = None


@pytest.mark.parametrize("target", ["submitted", "owned"])
@pytest.mark.parametrize(
    "cleanup",
    [KeyboardInterrupt("cleanup secret"), SystemExit("cleanup secret")],
)
def test_submit_submission_error_propagates_coroutine_cleanup_control(
    monkeypatch,
    caplog,
    target,
    cleanup,
):
    mgr = MCPManager({})
    mgr._loop = object()
    primary = RuntimeError("submission secret")
    coroutine = _CloseProbe(cleanup)

    def reject(submitted_coro, loop):
        assert loop is mgr._loop
        if target == "submitted":
            assert submitted_coro is coroutine
        raise primary

    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", reject)
    caplog.set_level(logging.WARNING, logger="forgeagent.mcp_manager")

    try:
        with pytest.raises(type(cleanup)) as raised:
            mgr._submit(
                coroutine,
                timeout=0.01,
                cancel_on_timeout=target != "submitted",
            )

        assert raised.value is cleanup
        assert coroutine.close_calls == 1
        assert "submission secret" not in caplog.text
        assert "cleanup secret" not in caplog.text
    finally:
        primary.__traceback__ = None
        cleanup.__traceback__ = None


@pytest.mark.parametrize("target", ["submitted", "owned"])
def test_submit_submission_and_coroutine_cleanup_errors_preserve_primary(
    monkeypatch,
    caplog,
    target,
):
    mgr = MCPManager({})
    mgr._loop = object()
    primary = RuntimeError("submission secret")
    cleanup = OSError("cleanup secret")
    coroutine = _CloseProbe(cleanup)

    monkeypatch.setattr(
        mcp_manager_module.asyncio,
        "run_coroutine_threadsafe",
        lambda submitted_coro, loop: (_ for _ in ()).throw(primary),
    )
    caplog.set_level(logging.WARNING, logger="forgeagent.mcp_manager")

    try:
        with pytest.raises(RuntimeError) as raised:
            mgr._submit(
                coroutine,
                timeout=0.01,
                cancel_on_timeout=target != "submitted",
            )

        assert raised.value is primary
        assert coroutine.close_calls == 1
        assert "submission secret" not in caplog.text
        assert "cleanup secret" not in caplog.text
    finally:
        primary.__traceback__ = None
        cleanup.__traceback__ = None


@pytest.mark.parametrize(
    "cleanup",
    [
        KeyboardInterrupt("cancel secret"),
        SystemExit("cancel secret"),
        OSError("cancel secret"),
    ],
)
def test_submit_timeout_delivers_ownership_before_selecting_cancel_error(
    monkeypatch,
    caplog,
    cleanup,
):
    primary = concurrent.futures.TimeoutError("timeout secret")
    future = _FutureProbe(error=primary, cancel_error=cleanup)
    coroutine = _CloseProbe()

    class QueuedLoop:
        def __init__(self):
            self.callbacks = []

        def call_soon_threadsafe(self, callback, *args):
            self.callbacks.append((callback, args))

    loop = QueuedLoop()
    mgr = MCPManager({})
    mgr._loop = loop

    def submit(submitted_coro, submitted_loop):
        assert submitted_loop is loop
        submitted_coro.close()
        return future

    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", submit)
    caplog.set_level(logging.WARNING, logger="forgeagent.mcp_manager")
    expected = cleanup if isinstance(cleanup, (KeyboardInterrupt, SystemExit)) else primary

    try:
        with pytest.raises(type(expected)) as raised:
            mgr._submit(coroutine, timeout=0.01)

        assert raised.value is expected
        assert future.cancel_calls == 1
        assert len(loop.callbacks) == 1
        operation = loop.callbacks[0][1][0]
        assert operation.coroutine is coroutine
        assert "timeout secret" not in caplog.text
        assert "cancel secret" not in caplog.text
    finally:
        if loop.callbacks:
            operation = loop.callbacks[0][1][0]
            if operation.coroutine is not None:
                operation.coroutine.close()
                operation.coroutine = None
        primary.__traceback__ = None
        cleanup.__traceback__ = None


@pytest.mark.parametrize(
    ("primary", "scheduling", "close_error", "selected"),
    [
        (
            concurrent.futures.TimeoutError("result secret"),
            KeyboardInterrupt("scheduling secret"),
            None,
            "scheduling",
        ),
        (
            RuntimeError("result secret"),
            SystemExit("scheduling secret"),
            None,
            "scheduling",
        ),
        (
            concurrent.futures.TimeoutError("result secret"),
            OSError("scheduling secret"),
            KeyboardInterrupt("close secret"),
            "close",
        ),
        (
            RuntimeError("result secret"),
            OSError("scheduling secret"),
            SystemExit("close secret"),
            "close",
        ),
        (
            concurrent.futures.TimeoutError("result secret"),
            OSError("scheduling secret"),
            ValueError("close secret"),
            "primary",
        ),
        (
            RuntimeError("result secret"),
            OSError("scheduling secret"),
            ValueError("close secret"),
            "primary",
        ),
    ],
)
def test_submit_result_failure_selects_must_deliver_cleanup_control(
    monkeypatch,
    caplog,
    primary,
    scheduling,
    close_error,
    selected,
):
    future = _FutureProbe(error=primary)
    coroutine = _CloseProbe(close_error)

    class FailingLoop:
        def __init__(self):
            self.schedule_calls = 0

        def call_soon_threadsafe(self, callback, *args):
            self.schedule_calls += 1
            raise scheduling

    loop = FailingLoop()
    mgr = MCPManager({})
    mgr._loop = loop

    def submit(submitted_coro, submitted_loop):
        assert submitted_loop is loop
        submitted_coro.close()
        return future

    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", submit)
    caplog.set_level(logging.WARNING, logger="forgeagent.mcp_manager")
    expected = {
        "primary": primary,
        "scheduling": scheduling,
        "close": close_error,
    }[selected]

    try:
        with pytest.raises(type(expected)) as raised:
            mgr._submit(coroutine, timeout=0.01)

        assert raised.value is expected
        assert loop.schedule_calls == 1
        assert coroutine.close_calls == 1
        assert "result secret" not in caplog.text
        assert "scheduling secret" not in caplog.text
        assert "close secret" not in caplog.text
    finally:
        primary.__traceback__ = None
        scheduling.__traceback__ = None
        if close_error is not None:
            close_error.__traceback__ = None


@pytest.mark.parametrize(
    ("source", "control"),
    [
        ("task creation cleanup", KeyboardInterrupt("control secret")),
        ("task creation cleanup", SystemExit("control secret")),
        ("operation", KeyboardInterrupt("control secret")),
        ("operation", SystemExit("control secret")),
    ],
)
def test_submit_transports_lifecycle_control_without_killing_real_loop(
    monkeypatch,
    source,
    control,
):
    mgr = MCPManager(
        {},
        shutdown_timeout=0.03,
        thread_join_timeout=0.02,
    )
    loop = asyncio.new_event_loop()
    loop_messages = []
    loop.set_exception_handler(lambda _loop, context: loop_messages.append(context["message"]))
    thread = threading.Thread(
        target=loop.run_forever,
        name="forgeagent-mcp-loop",
        daemon=True,
    )
    mgr._loop = loop
    mgr._thread = thread
    mgr._started = True
    original_create_task = asyncio.create_task
    original_submit = asyncio.run_coroutine_threadsafe
    primary = RuntimeError("create task secret")
    close_probe = None

    if source == "task creation cleanup":
        close_probe = _CloseProbe(control)
        operation_coro = close_probe
        monkeypatch.setattr(
            mcp_manager_module.asyncio,
            "create_task",
            lambda submitted_coro: (_ for _ in ()).throw(primary),
        )
    else:

        async def raise_control():
            await asyncio.sleep(0)
            raise control

        operation_coro = raise_control()

    caller_error = None
    loop_survived = False
    loop_usable = False
    close_error = None

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        thread.start()
        try:
            mgr._submit(operation_coro, timeout=0.05)
        except BaseException as exc:
            caller_error = exc

        thread.join(timeout=0.02)
        loop_survived = thread.is_alive()
        if loop_survived:
            try:
                original_submit(asyncio.sleep(0), loop).result(timeout=0.2)
            except BaseException:
                pass
            else:
                loop_usable = True

        monkeypatch.setattr(mcp_manager_module.asyncio, "create_task", original_create_task)
        if loop_survived:
            try:
                mgr.close()
            except BaseException as exc:
                close_error = exc
            thread.join(timeout=0.2)
        else:
            thread.join(timeout=0.2)
            mgr._lifecycle_tasks.clear()
            mgr._loop = None
            mgr._thread = None
            loop.close()
        gc.collect()

    diagnostic = {
        "caller_error": type(caller_error).__name__ if caller_error is not None else None,
        "exact_control": caller_error is control,
        "loop_survived": loop_survived,
        "loop_usable": loop_usable,
        "loop_messages": loop_messages,
        "warnings": [type(item.message).__name__ for item in caught],
    }

    try:
        assert diagnostic == {
            "caller_error": type(control).__name__,
            "exact_control": True,
            "loop_survived": True,
            "loop_usable": True,
            "loop_messages": [],
            "warnings": [],
        }
        assert close_error is None
        assert not thread.is_alive()
        assert loop.is_closed()
        assert mgr._lifecycle_tasks == set()
        if close_probe is not None:
            assert close_probe.close_calls == 1
    finally:
        primary.__traceback__ = None
        control.__traceback__ = None
        if not loop.is_closed():
            loop.close()


@pytest.mark.parametrize("error", [RuntimeError("operation secret"), asyncio.CancelledError()])
def test_submit_preserves_non_control_lifecycle_failure_on_real_loop(error):
    mgr = MCPManager({}, shutdown_timeout=0.03, thread_join_timeout=0.02)
    loop = asyncio.new_event_loop()
    loop_messages = []
    loop.set_exception_handler(lambda _loop, context: loop_messages.append(context["message"]))
    thread = threading.Thread(
        target=loop.run_forever,
        name="forgeagent-mcp-loop",
        daemon=True,
    )
    mgr._loop = loop
    mgr._thread = thread
    mgr._started = True

    async def fail_operation():
        await asyncio.sleep(0)
        raise error

    caller_error = None
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        thread.start()
        try:
            mgr._submit(fail_operation(), timeout=0.2)
        except BaseException as exc:
            caller_error = exc

        assert thread.is_alive()
        asyncio.run_coroutine_threadsafe(asyncio.sleep(0), loop).result(timeout=0.2)
        mgr.close()
        thread.join(timeout=0.2)
        gc.collect()

    try:
        if isinstance(error, asyncio.CancelledError):
            assert isinstance(caller_error, concurrent.futures.CancelledError)
        else:
            assert caller_error is error
        assert not thread.is_alive()
        assert loop.is_closed()
        assert mgr._lifecycle_tasks == set()
        assert loop_messages == []
        assert caught == []
    finally:
        error.__traceback__ = None
        if not loop.is_closed():
            loop.close()


@pytest.mark.parametrize(
    ("path", "primary", "cleanup"),
    [
        ("explicit enable", KeyboardInterrupt("primary secret"), OSError("cleanup secret")),
        ("explicit enable", RuntimeError("primary secret"), SystemExit("cleanup secret")),
        ("replacement", SystemExit("primary secret"), OSError("cleanup secret")),
        ("replacement", RuntimeError("primary secret"), KeyboardInterrupt("cleanup secret")),
    ],
)
def test_holder_task_creation_failure_isolated_on_real_loop(
    monkeypatch,
    path,
    primary,
    cleanup,
):
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        connect_timeout=0.05,
        shutdown_timeout=0.03,
        thread_join_timeout=0.02,
    )
    loop = asyncio.new_event_loop()
    loop_messages = []
    loop.set_exception_handler(lambda _loop, context: loop_messages.append(context["message"]))
    thread = threading.Thread(
        target=loop.run_forever,
        name="forgeagent-mcp-loop",
        daemon=True,
    )
    mgr._loop = loop
    mgr._thread = thread
    mgr._started = True
    original_create_task = asyncio.create_task
    original_submit = asyncio.run_coroutine_threadsafe
    holder_coro = _CloseProbe(cleanup)
    monkeypatch.setattr(mgr, "_holder", lambda *args: holder_coro)

    def fail_holder_task_creation(submitted_coro):
        if submitted_coro is holder_coro:
            raise primary
        return original_create_task(submitted_coro)

    monkeypatch.setattr(
        mcp_manager_module.asyncio,
        "create_task",
        fail_holder_task_creation,
    )
    caller_error = None
    operation_completed = False

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        thread.start()
        if path == "explicit enable":
            try:
                operation_completed = mgr.enable("pending")
            except BaseException as exc:
                caller_error = exc
        else:
            finalized = threading.Event()

            async def install_old_holder() -> None:
                stop = asyncio.Event()

                async def old_holder() -> None:
                    await asyncio.sleep(0)

                task = asyncio.create_task(old_holder())
                state = mgr._states["pending"]
                state.generation = 1
                state.status = "restarting"
                state.tearing_down_generation = 1
                state.restart_after_generation = 1
                mgr._holders["pending"] = (1, task, stop)

                def finalize(done):
                    try:
                        mgr._finalize_holder_slot("pending", 1, done)
                    finally:
                        finalized.set()

                task.add_done_callback(finalize)
                await asyncio.sleep(0)

            try:
                original_submit(install_old_holder(), loop).result(timeout=0.2)
                operation_completed = finalized.wait(timeout=0.2)
            except BaseException as exc:
                caller_error = exc

        thread.join(timeout=0.02)
        loop_survived = thread.is_alive()
        loop_usable = False
        if loop_survived:
            try:
                original_submit(asyncio.sleep(0), loop).result(timeout=0.2)
            except BaseException:
                pass
            else:
                loop_usable = True

        state = mgr._states["pending"]
        selected = primary if isinstance(primary, (KeyboardInterrupt, SystemExit)) else cleanup
        diagnostic = {
            "caller_error": caller_error,
            "operation_completed": operation_completed,
            "loop_survived": loop_survived,
            "loop_usable": loop_usable,
            "status": mgr.server_status()["pending"],
            "generation": state.generation,
            "holders": dict(mgr._holders),
            "sessions": dict(mgr._sessions),
            "tools": list(state.tools),
            "tearing_down": state.tearing_down_generation,
            "restart_after": state.restart_after_generation,
        }

        monkeypatch.setattr(mcp_manager_module.asyncio, "create_task", original_create_task)
        if loop_survived:
            mgr.close()
            thread.join(timeout=0.2)
        else:
            thread.join(timeout=0.2)
            mgr._holders.clear()
            mgr._sessions.clear()
            mgr._lifecycle_tasks.clear()
            mgr._loop = None
            mgr._thread = None
            loop.close()
        gc.collect()

    try:
        assert diagnostic == {
            "caller_error": None,
            "operation_completed": True,
            "loop_survived": True,
            "loop_usable": True,
            "status": f"unavailable: {type(selected).__name__}",
            "generation": 1 if path == "explicit enable" else 2,
            "holders": {},
            "sessions": {},
            "tools": [],
            "tearing_down": None,
            "restart_after": None,
        }
        assert holder_coro.close_calls == 1
        assert loop_messages == []
        assert caught == []
        assert not thread.is_alive()
        assert loop.is_closed()
    finally:
        primary.__traceback__ = None
        cleanup.__traceback__ = None
        if not loop.is_closed():
            loop.close()


def test_disable_facade_timeout_does_not_discard_queued_lifecycle_intent():
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        connect_timeout=-4.98,
        shutdown_timeout=0.03,
        thread_join_timeout=0.02,
    )
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    blocked = threading.Event()
    release = threading.Event()
    mgr._loop = loop
    mgr._thread = thread
    thread.start()

    def block_loop() -> None:
        blocked.set()
        release.wait(timeout=1)

    loop.call_soon_threadsafe(block_loop)
    assert blocked.wait(timeout=1)

    try:
        with pytest.raises(concurrent.futures.TimeoutError):
            mgr.disable("pending")

        assert mgr._states["pending"].config.enabled is True
        release.set()
        deadline = time.monotonic() + 1
        while mgr._states["pending"].config.enabled and time.monotonic() < deadline:
            time.sleep(0.005)

        assert mgr._states["pending"].config.enabled is False
        assert mgr.server_status()["pending"] == "unavailable: disabled"
    finally:
        release.set()
        mgr.close()
        if thread.is_alive():
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=1)
        if not loop.is_closed():
            loop.close()


def test_enable_facade_timeout_delivers_intent_and_closes_cleanly(monkeypatch):
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        connect_timeout=-4.98,
        shutdown_timeout=0.03,
        thread_join_timeout=0.02,
    )
    loop = asyncio.new_event_loop()
    loop_messages = []
    loop.set_exception_handler(lambda _loop, context: loop_messages.append(context["message"]))
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    blocked = threading.Event()
    release = threading.Event()
    intent_ran = threading.Event()
    mgr._loop = loop
    mgr._thread = thread

    async def holder(name, generation, ready, stop):
        intent_ran.set()
        ready.set()
        await stop.wait()

    def block_loop() -> None:
        blocked.set()
        release.wait(timeout=1)

    monkeypatch.setattr(mgr, "_holder", holder)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        thread.start()
        loop.call_soon_threadsafe(block_loop)
        assert blocked.wait(timeout=1)
        started = time.monotonic()
        try:
            with pytest.raises(concurrent.futures.TimeoutError):
                mgr.enable("pending")
            assert time.monotonic() - started < 0.5

            release.set()
            assert intent_ran.wait(timeout=1)
            deadline = time.monotonic() + 1
            while mgr._lifecycle_tasks and time.monotonic() < deadline:
                time.sleep(0.005)
            assert mgr._lifecycle_tasks == set()
            assert mgr.close() is None
            thread.join(timeout=1)
            gc.collect()
        finally:
            release.set()
            if thread.is_alive():
                loop.call_soon_threadsafe(loop.stop)
                thread.join(timeout=1)
            if not loop.is_closed():
                loop.close()

    assert not thread.is_alive()
    assert loop.is_closed()
    assert loop_messages == []
    assert not any(isinstance(item.message, RuntimeWarning) for item in caught)


@pytest.mark.parametrize(
    "facade_error",
    [concurrent.futures.TimeoutError(), concurrent.futures.CancelledError()],
)
def test_lifecycle_fallback_start_failure_reports_fixed_type(monkeypatch, caplog, facade_error):
    mgr = MCPManager({})
    future = _FutureProbe(error=facade_error)

    class ImmediateLoop:
        def call_soon_threadsafe(self, callback, *args):
            callback(*args)

    def timeout_submission(coro, loop):
        coro.close()
        return future

    mgr._loop = ImmediateLoop()
    monkeypatch.setattr(
        mcp_manager_module.asyncio,
        "run_coroutine_threadsafe",
        timeout_submission,
    )
    caplog.set_level(logging.WARNING, logger="forgeagent.mcp_manager")

    with pytest.raises(type(facade_error)):
        mgr._submit(asyncio.sleep(0), timeout=0.01)

    assert "MCP lifecycle operation start failed: RuntimeError" in caplog.text
    assert "no running event loop" not in caplog.text


def test_server_status_masks_secret_bearing_exception_text(monkeypatch):
    secret = "optional-status-secret"
    monkeypatch.setattr("forgeagent.mcp_manager.sensitive_env_values", lambda: {secret})
    mgr = MCPManager({"optional": MCPServerConfig(command="unused")})
    mgr._states["optional"].status = f"unavailable: RuntimeError: {secret}"

    status = mgr.server_status()["optional"]

    assert secret not in status
    assert status == "unavailable: RuntimeError"


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


def test_discovery_masks_descriptions_excludes_sensitive_names_and_routes_safe_tool(monkeypatch):
    secret = "discovery-secret"
    monkeypatch.setattr(mcp_manager_module, "sensitive_env_values", lambda: {secret})
    manager = MCPManager({"server": MCPServerConfig(command="unused")})
    raw_tools = [
        type("Tool", (), {"name": "safe", "description": f"safe {secret}"})(),
        type("Tool", (), {"name": f"unsafe-{secret}", "description": "hidden"})(),
    ]
    state = manager._states["server"]
    state.generation = 1
    state.status = "available"
    state.tools = manager._filter_tools("server", state.config, raw_tools)

    listed = manager.list_tools()
    prompt = manager.tools_prompt()

    assert [tool.name for tool in listed] == ["safe"]
    assert secret not in listed[0].description
    assert secret not in prompt

    async def route_safe_tool() -> tuple[dict, _SessionProbe]:
        stop = asyncio.Event()
        holder = asyncio.create_task(asyncio.Event().wait())
        session = _SessionProbe("ok")
        manager._holders["server"] = (1, holder, stop)
        manager._sessions["server"] = (1, session)
        try:
            return await manager._call_tool_on_loop("server", "safe", {}), session
        finally:
            holder.cancel()
            await asyncio.gather(holder, return_exceptions=True)

    result, session = asyncio.run(route_safe_tool())
    assert result == {"ok": True, "text": "ok"}
    assert session.call_count == 1


def test_discovery_excludes_sensitive_server_identity_from_public_catalog(monkeypatch):
    secret = "server-identity-secret"
    server = f"external-{secret}"
    monkeypatch.setattr(mcp_manager_module, "sensitive_env_values", lambda: {secret})
    manager = MCPManager({server: MCPServerConfig(command="unused", required=True)})
    state = manager._states[server]
    state.status = "available"
    state.tools = manager._filter_tools(
        server,
        state.config,
        [type("Tool", (), {"name": "safe", "description": "safe description"})()],
    )

    assert manager.list_tools() == []
    assert manager.tools_prompt() == ""

    state.status = "unavailable: RuntimeError"
    assert secret not in repr(manager.server_status())
    assert secret not in repr(manager.required_failures())


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
        mgr._states["normal"].generation = 1
        mgr._states["cancel-only"].generation = 1
        mgr._sessions.update({"normal": (1, object()), "cancel-only": (1, object())})

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

        mgr._holders["normal"] = (1, asyncio.create_task(normal_holder()), normal_stop)
        mgr._holders["cancel-only"] = (
            1,
            asyncio.create_task(cancel_only_holder()),
            cancel_only_stop,
        )

    asyncio.run_coroutine_threadsafe(install_holders(), loop).result(timeout=1)
    started = time.monotonic()
    try:
        assert mgr.close() is None
    finally:
        if thread.is_alive():

            async def cancel_test_holders() -> None:
                holders = [slot[1] for slot in mgr._holders.values()]
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
        stop = asyncio.Event()
        mgr._states["pending"].generation = 1
        mgr._sessions["pending"] = (1, session)

        async def holder() -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellation_cleanup.set()
                raise
            finally:
                cleanup_thread_ids.append(threading.get_ident())
                mgr._sessions.pop("pending", None)

        mgr._holders["pending"] = (1, asyncio.create_task(holder()), stop)

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
            assert mgr._sessions == {"pending": (1, session)}
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


def test_repeated_close_reuses_one_loop_owned_shutdown_task_and_snapshot(monkeypatch):
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
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
    cleanup_finished = threading.Event()
    loop_state: dict[str, asyncio.Event] = {}
    submissions = 0
    mgr._loop = loop
    mgr._thread = thread
    thread.start()

    async def install_holder() -> None:
        stop = asyncio.Event()
        cleanup_release = asyncio.Event()
        loop_state["cleanup_release"] = cleanup_release
        mgr._states["pending"].generation = 1
        mgr._states["pending"].status = "available"
        session = object()
        mgr._sessions["pending"] = (1, session)

        async def holder() -> None:
            try:
                await stop.wait()
            finally:
                cleanup_started.set()
                while not cleanup_release.is_set():
                    try:
                        await cleanup_release.wait()
                    except asyncio.CancelledError:
                        pass
                if mgr._sessions.get("pending") == (1, session):
                    mgr._sessions.pop("pending", None)
                cleanup_finished.set()

        mgr._holders["pending"] = (1, asyncio.create_task(holder()), stop)

    original_submit = asyncio.run_coroutine_threadsafe
    original_submit(install_holder(), loop).result(timeout=1)

    def count_submission(coro, submitted_loop):
        nonlocal submissions
        submissions += 1
        return original_submit(coro, submitted_loop)

    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", count_submission)

    try:
        assert mgr.close() is None
        assert cleanup_started.wait(timeout=1)
        shutdown_task = mgr._shutdown_task
        shutdown_snapshot = mgr._shutdown_snapshot
        shutdown_future = mgr._shutdown_future
        assert shutdown_task is not None
        assert shutdown_snapshot is not None
        assert submissions == 1

        assert mgr.close() is None

        assert mgr._shutdown_task is shutdown_task
        assert mgr._shutdown_snapshot is shutdown_snapshot
        assert mgr._shutdown_future is shutdown_future
        assert submissions == 1

        loop.call_soon_threadsafe(loop_state["cleanup_release"].set)
        assert cleanup_finished.wait(timeout=1)
        thread.join(timeout=1)
        assert not thread.is_alive()

        assert mgr.close() is None
        assert submissions == 1
        assert mgr._loop is None
        assert mgr._thread is None
    finally:
        if "cleanup_release" in loop_state and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(loop_state["cleanup_release"].set)
            except RuntimeError:
                pass
        if thread.is_alive():
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=1)
        if not loop.is_closed():
            loop.close()


def test_shutdown_stops_holder_before_stubborn_lifecycle_retry():
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        shutdown_timeout=0.03,
        thread_join_timeout=0.02,
    )
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    holder_stopped = threading.Event()
    lifecycle_cancelled_once = threading.Event()
    lifecycle_finished = threading.Event()
    allow_lifecycle_finish = threading.Event()
    mgr._loop = loop
    mgr._thread = thread
    thread.start()

    async def install_resources() -> None:
        stop = asyncio.Event()

        async def holder() -> None:
            await stop.wait()
            holder_stopped.set()

        async def stubborn_lifecycle() -> None:
            while True:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    lifecycle_cancelled_once.set()
                    if allow_lifecycle_finish.is_set():
                        lifecycle_finished.set()
                        raise

        holder_task = asyncio.create_task(holder())
        lifecycle_task = asyncio.create_task(stubborn_lifecycle())
        mgr._states["pending"].generation = 1
        mgr._holders["pending"] = (1, holder_task, stop)
        mgr._lifecycle_tasks.add(lifecycle_task)

    asyncio.run_coroutine_threadsafe(install_resources(), loop).result(timeout=1)

    try:
        assert mgr.close() is None
        assert holder_stopped.wait(timeout=1)
        assert lifecycle_cancelled_once.wait(timeout=1)
        assert not lifecycle_finished.is_set()
        assert mgr._shutdown_complete.is_set() is False

        allow_lifecycle_finish.set()
        assert mgr.close() is None
        assert lifecycle_finished.wait(timeout=1)
        thread.join(timeout=1)
        assert not thread.is_alive()
        assert mgr._shutdown_complete.is_set()

        assert mgr.close() is None
        assert mgr._loop is None
        assert mgr._thread is None
    finally:
        if thread.is_alive():
            for task in list(mgr._lifecycle_tasks):
                loop.call_soon_threadsafe(task.cancel)
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=1)
        if not loop.is_closed():
            loop.close()


def test_shutdown_signals_holder_stop_before_lifecycle_cancel():
    events: list[str] = []

    async def run_shutdown() -> None:
        mgr = MCPManager(
            {"pending": MCPServerConfig(command="unused")},
            shutdown_timeout=0.1,
            thread_join_timeout=0.02,
        )
        loop = asyncio.get_running_loop()

        class RecordingStop(asyncio.Event):
            def set(self) -> None:
                events.append("holder-stop")
                super().set()

        class RecordingLifecycleTask(asyncio.Task):
            def cancel(self, msg=None):
                events.append("lifecycle-cancel")
                return super().cancel(msg)

        stop = RecordingStop()

        async def holder() -> None:
            await stop.wait()

        async def lifecycle() -> None:
            await asyncio.Event().wait()

        holder_task = asyncio.create_task(holder())
        lifecycle_task = RecordingLifecycleTask(lifecycle(), loop=loop)
        mgr._states["pending"].generation = 1
        mgr._holders["pending"] = (1, holder_task, stop)
        mgr._lifecycle_tasks.add(lifecycle_task)

        async def keep_test_loop_running() -> None:
            pass

        mgr._stop_loop_after_facades = keep_test_loop_running
        await mgr._ensure_shutdown_task(time.monotonic() + 0.1)

        assert events[:2] == ["holder-stop", "lifecycle-cancel"]
        assert mgr._shutdown_complete.is_set()

    asyncio.run(run_shutdown())


def test_shutdown_isolates_ordinary_lifecycle_cancel_failure():
    async def run_shutdown() -> None:
        mgr = MCPManager({}, shutdown_timeout=0.1, thread_join_timeout=0.02)
        loop = asyncio.get_running_loop()

        class FailOnceCancelTask(asyncio.Task):
            cancel_calls = 0

            def cancel(self, msg=None):
                self.cancel_calls += 1
                if self.cancel_calls == 1:
                    raise RuntimeError("cancel failed")
                return super().cancel(msg)

        async def lifecycle() -> None:
            await asyncio.Event().wait()

        lifecycle_task = FailOnceCancelTask(lifecycle(), loop=loop)
        mgr._lifecycle_tasks.add(lifecycle_task)

        async def keep_test_loop_running() -> None:
            pass

        mgr._stop_loop_after_facades = keep_test_loop_running
        await mgr._ensure_shutdown_task(time.monotonic() + 0.1)

        assert lifecycle_task.cancel_calls >= 2
        assert lifecycle_task.cancelled()
        assert mgr._lifecycle_tasks == set()
        assert mgr._shutdown_complete.is_set()

    asyncio.run(run_shutdown())


def test_repeated_close_recreates_join_deadline_from_current_clock(monkeypatch):
    mgr = MCPManager({}, shutdown_timeout=0.03, thread_join_timeout=0.02)
    mgr._closed = True
    mgr._loop = _LoopProbe()
    mgr._thread = _ThreadProbe(alive=True)
    mgr._shutdown_future = _FutureProbe()
    mgr._shutdown_complete.set()
    deadlines: list[tuple[float, frozenset[str]]] = []
    clock = iter([100.0, 100.0, 250.0, 250.0])

    monkeypatch.setattr(mcp_manager_module.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(
        mgr,
        "_stop_and_join",
        lambda deadline, pending: deadlines.append((deadline, pending)),
    )

    mgr.close()
    mgr.close()

    assert deadlines == [(100.05, frozenset()), (250.05, frozenset())]
    assert mgr._shutdown_future.cancel_calls == 0


def test_close_uses_single_deadline_for_facade_and_join(monkeypatch):
    mgr = MCPManager({}, shutdown_timeout=0.3, thread_join_timeout=0.2)
    loop = _LoopProbe()
    thread = _ThreadProbe(alive=True, alive_results=[True, False])
    future = _FutureProbe()
    mgr._loop = loop
    mgr._thread = thread
    mgr._shutdown_complete.set()
    clock = iter([100.0, 100.1, 100.4])

    def submit(coro, submitted_loop):
        assert submitted_loop is loop
        coro.close()
        return future

    monkeypatch.setattr(mcp_manager_module.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", submit)

    assert mgr.close() is None

    assert future.result_timeouts == pytest.approx([0.2])
    assert thread.join_timeouts == pytest.approx([0.1])


def test_close_wall_clock_is_bounded_by_shutdown_and_join_budgets(monkeypatch):
    mgr = MCPManager({}, shutdown_timeout=0.03, thread_join_timeout=0.02)
    loop = _LoopProbe()
    thread = _ThreadProbe(alive=True, wait_for_timeout=True)
    future = _FutureProbe(wait_for_timeout=True)
    mgr._loop = loop
    mgr._thread = thread
    mgr._shutdown_complete.set()

    def submit(coro, submitted_loop):
        assert submitted_loop is loop
        coro.close()
        return future

    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", submit)

    started = time.monotonic()
    assert mgr.close() is None
    elapsed = time.monotonic() - started

    assert elapsed <= mgr._shutdown_timeout + mgr._thread_join_timeout + 0.03


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


def test_connect_start_failure_survives_cancel_event_cleanup_error(monkeypatch):
    mgr = MCPManager({"pending": MCPServerConfig(command="unused")})
    loop = asyncio.new_event_loop()
    primary = KeyboardInterrupt()
    original_event = threading.Event
    event_calls = 0

    class CancelFailureEvent:
        def set(self):
            raise asyncio.CancelledError

    def event_factory():
        nonlocal event_calls
        event_calls += 1
        return CancelFailureEvent() if event_calls == 2 else original_event()

    def fail_start(thread):
        raise primary

    monkeypatch.setattr(mcp_manager_module.asyncio, "new_event_loop", lambda: loop)
    monkeypatch.setattr(mcp_manager_module.threading, "Event", event_factory)
    monkeypatch.setattr(mcp_manager_module.threading.Thread, "start", fail_start)

    try:
        with pytest.raises(KeyboardInterrupt) as raised:
            mgr.connect()

        assert raised.value is primary
        assert mgr._started is False
        assert mgr._loop is None
        assert mgr._thread is None
        assert loop.is_closed()
    finally:
        primary.__traceback__ = None
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


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(7)])
def test_connect_interrupt_releasing_publication_gate_stops_running_loop(monkeypatch, error):
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        thread_join_timeout=0.2,
    )
    loop = asyncio.new_event_loop()
    original_event = threading.Event

    class InterruptingGate:
        def __init__(self) -> None:
            self._event = original_event()
            self._interrupted = False

        def wait(self, timeout=None) -> bool:
            return self._event.wait(timeout)

        def set(self) -> None:
            self._event.set()
            if self._interrupted:
                return
            self._interrupted = True
            deadline = time.monotonic() + 0.2
            while not loop.is_running() and time.monotonic() < deadline:
                time.sleep(0.001)
            raise error

    gate = InterruptingGate()
    event_calls = 0

    def event_factory():
        nonlocal event_calls
        event_calls += 1
        return gate if event_calls == 1 else original_event()

    monkeypatch.setattr(mcp_manager_module.asyncio, "new_event_loop", lambda: loop)
    monkeypatch.setattr(mcp_manager_module.threading, "Event", event_factory)

    try:
        with pytest.raises(type(error)) as raised:
            mgr.connect()

        assert raised.value is error
        assert mgr._started is False
        assert mgr._loop is None
        assert mgr._thread is None
        assert loop.is_closed()
    finally:
        error.__traceback__ = None
        if mgr._thread is not None and mgr._thread.is_alive():
            loop.call_soon_threadsafe(loop.stop)
            mgr._thread.join(timeout=1)
        if not loop.is_closed():
            loop.close()


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(7)])
def test_connect_gate_release_before_set_preserves_exception_and_stops_worker(monkeypatch, error):
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        thread_join_timeout=0.2,
    )
    loop = asyncio.new_event_loop()
    original_event = threading.Event
    started_threads: list[threading.Thread] = []
    original_start = threading.Thread.start

    class NeverReleasedGate:
        def wait(self, timeout=None):
            time.sleep(0.005 if timeout is None else min(timeout, 0.005))
            return False

        def set(self):
            raise error

    gate = NeverReleasedGate()
    event_calls = 0

    def event_factory():
        nonlocal event_calls
        event_calls += 1
        return gate if event_calls == 1 else original_event()

    def record_start(thread):
        original_start(thread)
        started_threads.append(thread)

    monkeypatch.setattr(mcp_manager_module.asyncio, "new_event_loop", lambda: loop)
    monkeypatch.setattr(mcp_manager_module.threading, "Event", event_factory)
    monkeypatch.setattr(mcp_manager_module.threading.Thread, "start", record_start)

    try:
        with pytest.raises(type(error)) as raised:
            mgr.connect()

        assert raised.value is error
        assert started_threads
        assert not started_threads[0].is_alive()
        assert mgr._started is False
        assert mgr._loop is None
        assert mgr._thread is None
        assert loop.is_closed()
    finally:
        error.__traceback__ = None
        if started_threads and started_threads[0].is_alive():
            loop.call_soon_threadsafe(loop.stop)
            started_threads[0].join(timeout=1)
        if not loop.is_closed():
            loop.close()


def test_connect_startup_rollback_retries_stopped_loop_close(monkeypatch, caplog):
    secret = "startup-loop-close-secret"
    primary = KeyboardInterrupt()
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        thread_join_timeout=0.2,
    )
    real_loop = asyncio.new_event_loop()
    original_event = threading.Event
    event_calls = 0

    class FailOnceCloseLoop:
        def __init__(self) -> None:
            self.close_calls = 0

        def __getattr__(self, name):
            return getattr(real_loop, name)

        def close(self) -> None:
            self.close_calls += 1
            if self.close_calls == 1:
                raise OSError(f"close failed: {secret}")
            real_loop.close()

    class NeverReleasedGate:
        def wait(self, timeout=None):
            time.sleep(0.005 if timeout is None else min(timeout, 0.005))
            return False

        def set(self):
            raise primary

    loop = FailOnceCloseLoop()

    def event_factory():
        nonlocal event_calls
        event_calls += 1
        return NeverReleasedGate() if event_calls == 1 else original_event()

    monkeypatch.setattr(mcp_manager_module.asyncio, "new_event_loop", lambda: loop)
    monkeypatch.setattr(mcp_manager_module.threading, "Event", event_factory)
    caplog.set_level(logging.WARNING, logger="forgeagent.mcp_manager")

    try:
        with pytest.raises(KeyboardInterrupt) as raised:
            mgr.connect()

        assert raised.value is primary
        assert mgr._started is True
        assert mgr._closed is True
        assert mgr._loop is loop
        assert mgr._thread is not None and not mgr._thread.is_alive()
        assert mgr._shutdown_complete.is_set()
        assert loop.close_calls == 1
        assert "MCP loop cleanup after start failure failed: OSError" in caplog.text
        assert secret not in caplog.text

        assert mgr.close() is None

        assert loop.close_calls == 2
        assert real_loop.is_closed()
        assert mgr._loop is None
        assert mgr._thread is None
    finally:
        primary.__traceback__ = None
        if mgr._thread is not None and mgr._thread.is_alive():
            real_loop.call_soon_threadsafe(real_loop.stop)
            mgr._thread.join(timeout=1)
        if not real_loop.is_closed():
            real_loop.close()


def test_connect_startup_rollback_retains_live_worker_until_close_retry(monkeypatch, caplog):
    secret = "startup-warning-secret"
    primary = KeyboardInterrupt()
    mgr = MCPManager(
        {secret: MCPServerConfig(command="unused")},
        thread_join_timeout=0.01,
    )
    loop = asyncio.new_event_loop()
    original_event = threading.Event
    release_worker = original_event()
    worker_waiting = original_event()
    event_calls = 0

    class StubbornGate:
        def wait(self, timeout=None):
            worker_waiting.set()
            release_worker.wait()
            return False

        def set(self):
            raise primary

    def event_factory():
        nonlocal event_calls
        event_calls += 1
        return StubbornGate() if event_calls == 1 else original_event()

    monkeypatch.setattr(mcp_manager_module.asyncio, "new_event_loop", lambda: loop)
    monkeypatch.setattr(mcp_manager_module.threading, "Event", event_factory)
    caplog.set_level(logging.WARNING, logger="forgeagent.mcp_manager")

    try:
        with pytest.raises(KeyboardInterrupt) as raised:
            mgr.connect()

        assert raised.value is primary
        assert worker_waiting.is_set()
        assert mgr._started is True
        assert mgr._closed is True
        assert mgr._loop is loop
        assert mgr._thread is not None and mgr._thread.is_alive()
        assert mgr._shutdown_complete.is_set()
        assert "startup cleanup incomplete" in caplog.text
        assert secret not in caplog.text

        release_worker.set()
        mgr._thread.join(timeout=1)
        assert not mgr._thread.is_alive()

        assert mgr.close() is None
        assert loop.is_closed()
        assert mgr._loop is None
        assert mgr._thread is None
    finally:
        primary.__traceback__ = None
        release_worker.set()
        if mgr._thread is not None and mgr._thread.is_alive():
            mgr._thread.join(timeout=1)
        if not loop.is_closed():
            loop.close()


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(7)])
def test_connect_initial_submission_control_exception_preserves_identity_and_cleans_up(
    monkeypatch, error
):
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        thread_join_timeout=0.2,
    )

    def fail_submit(coro, timeout):
        coro.close()
        raise error

    monkeypatch.setattr(mgr, "_submit", fail_submit)
    try:
        with pytest.raises(type(error)) as raised:
            mgr.connect()

        assert raised.value is error
        assert mgr._closed is True
        assert mgr._loop is None
        assert mgr._thread is None
    finally:
        error.__traceback__ = None
        if mgr._loop is not None and mgr._thread is not None and mgr._thread.is_alive():
            mgr._loop.call_soon_threadsafe(mgr._loop.stop)
            mgr._thread.join(timeout=1)
        if mgr._loop is not None and not mgr._loop.is_closed():
            mgr._loop.close()


def test_connect_control_exception_survives_secondary_cancelled_cleanup(monkeypatch):
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        thread_join_timeout=0.2,
    )
    primary = KeyboardInterrupt()

    def fail_submit(coro, timeout):
        coro.close()
        raise primary

    real_close = mgr.close
    monkeypatch.setattr(mgr, "_submit", fail_submit)
    monkeypatch.setattr(mgr, "close", lambda: (_ for _ in ()).throw(asyncio.CancelledError()))

    try:
        with pytest.raises(KeyboardInterrupt) as raised:
            mgr.connect()

        assert raised.value is primary
    finally:
        primary.__traceback__ = None
        real_close()


@pytest.mark.parametrize(
    ("failure_at", "primary", "cleanup", "later_cleanup", "selected"),
    [
        (
            "start",
            RuntimeError("startup secret"),
            KeyboardInterrupt("first cleanup secret"),
            SystemExit("later cleanup secret"),
            "cleanup",
        ),
        (
            "gate",
            RuntimeError("startup secret"),
            SystemExit("first cleanup secret"),
            KeyboardInterrupt("later cleanup secret"),
            "cleanup",
        ),
        (
            "start",
            KeyboardInterrupt("startup secret"),
            SystemExit("first cleanup secret"),
            RuntimeError("later cleanup secret"),
            "primary",
        ),
        (
            "gate",
            SystemExit("startup secret"),
            KeyboardInterrupt("first cleanup secret"),
            RuntimeError("later cleanup secret"),
            "primary",
        ),
    ],
)
def test_connect_startup_transaction_selects_first_control_after_bounded_cleanup(
    monkeypatch,
    caplog,
    failure_at,
    primary,
    cleanup,
    later_cleanup,
    selected,
):
    mgr = MCPManager({"pending": MCPServerConfig(command="unused")})

    class EventProbe:
        def __init__(self, errors):
            self.errors = list(errors)
            self.set_calls = 0

        def set(self):
            self.set_calls += 1
            if self.errors:
                raise self.errors.pop(0)

    gate_errors = [later_cleanup] if failure_at == "start" else [primary, later_cleanup]
    gate = EventProbe(gate_errors)
    cancelled = EventProbe([cleanup])
    events = iter([gate, cancelled])

    class StartupLoop:
        def __init__(self):
            self.schedule_calls = 0
            self.stop_calls = 0
            self.close_calls = 0

        def stop(self):
            self.stop_calls += 1

        def call_soon_threadsafe(self, callback):
            self.schedule_calls += 1
            callback()
            raise OSError("loop scheduling cleanup secret")

        def close(self):
            self.close_calls += 1

    loop = StartupLoop()

    class StartupThread:
        ident = 31415

        def __init__(self):
            self.start_calls = 0
            self.join_calls = 0
            self.alive_calls = 0

        def start(self):
            self.start_calls += 1
            if failure_at == "start":
                raise primary

        def join(self, timeout):
            self.join_calls += 1
            raise ValueError("join cleanup secret")

        def is_alive(self):
            self.alive_calls += 1
            return False

    thread = StartupThread()
    monkeypatch.setattr(mcp_manager_module.asyncio, "new_event_loop", lambda: loop)
    monkeypatch.setattr(mcp_manager_module.threading, "Event", lambda: next(events))
    monkeypatch.setattr(mcp_manager_module.threading, "Thread", lambda **kwargs: thread)
    caplog.set_level(logging.WARNING, logger="forgeagent.mcp_manager")
    expected = primary if selected == "primary" else cleanup

    try:
        with pytest.raises(type(expected)) as raised:
            mgr.connect()

        assert raised.value is expected
        assert thread.start_calls == 1
        assert cancelled.set_calls == 1
        assert gate.set_calls == (1 if failure_at == "start" else 2)
        assert loop.schedule_calls == 1
        assert loop.stop_calls == 1
        assert thread.join_calls == 1
        assert thread.alive_calls == 1
        assert loop.close_calls == 1
        assert mgr._started is False
        assert mgr._loop is None
        assert mgr._thread is None
        assert "startup secret" not in caplog.text
        assert "first cleanup secret" not in caplog.text
        assert "later cleanup secret" not in caplog.text
        assert "loop scheduling cleanup secret" not in caplog.text
        assert "join cleanup secret" not in caplog.text
    finally:
        primary.__traceback__ = None
        cleanup.__traceback__ = None
        later_cleanup.__traceback__ = None


def test_connect_initial_submission_exception_cleans_up_before_reraising(monkeypatch):
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        thread_join_timeout=0.2,
    )
    error = RuntimeError("secret infrastructure detail")

    def fail_submit(coro, timeout):
        coro.close()
        raise error

    monkeypatch.setattr(mgr, "_submit", fail_submit)

    with pytest.raises(RuntimeError) as raised:
        mgr.connect()

    assert raised.value is error
    assert mgr._closed is True
    assert mgr._loop is None
    assert mgr._thread is None


def test_connect_close_racing_partial_start_does_not_allocate_next_generation(monkeypatch):
    mgr = MCPManager(
        {
            "one": MCPServerConfig(command="unused"),
            "two": MCPServerConfig(command="unused"),
        },
        connect_timeout=0.01,
        shutdown_timeout=0.03,
        thread_join_timeout=0.02,
    )
    primary = KeyboardInterrupt()
    first_created = threading.Event()
    release_creation = threading.Event()
    second_created = threading.Event()
    original_submit = asyncio.run_coroutine_threadsafe
    submission_count = 0

    async def holder(stop: asyncio.Event, *, finish_immediately: bool) -> None:
        if finish_immediately:
            await asyncio.sleep(0)
        else:
            await stop.wait()

    def staged_start(name: str) -> asyncio.Event:
        state = mgr._states[name]
        state.generation += 1
        ready = asyncio.Event()
        stop = asyncio.Event()
        task = asyncio.create_task(holder(stop, finish_immediately=name == "two"))
        mgr._holders[name] = (state.generation, task, stop)
        if name == "one":
            first_created.set()
            release_creation.wait()
        else:
            second_created.set()
        return ready

    class InterruptingFacade:
        def __init__(self, actual):
            self.actual = actual

        def result(self, timeout):
            assert first_created.wait(timeout=1)
            raise primary

        def cancel(self):
            return self.actual.cancel()

    def submit(coro, loop):
        nonlocal submission_count
        submission_count += 1
        actual = original_submit(coro, loop)
        return InterruptingFacade(actual) if submission_count == 1 else actual

    monkeypatch.setattr(mgr, "_start_holder", staged_start)
    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", submit)

    try:
        with pytest.raises(KeyboardInterrupt) as raised:
            mgr.connect()

        assert raised.value is primary
        release_creation.set()
        assert not second_created.wait(timeout=0.1)
        assert mgr._states["two"].generation == 0
        assert mgr._thread is not None
        mgr._thread.join(timeout=1)
        assert not mgr._thread.is_alive()
        assert mgr._shutdown_complete.is_set()
        assert mgr._holders == {}
        assert mgr._sessions == {}
    finally:
        primary.__traceback__ = None
        release_creation.set()
        mgr.close()
        if mgr._thread is not None and mgr._thread.is_alive():
            mgr._loop.call_soon_threadsafe(mgr._loop.stop)
            mgr._thread.join(timeout=1)
        if mgr._loop is not None and not mgr._loop.is_closed():
            mgr._loop.close()


def test_connect_with_no_enabled_servers_remains_prestart_and_can_retry():
    mgr = MCPManager({"pending": _server("pending", enabled=False)})

    mgr.connect()

    assert mgr._started is False
    assert mgr._loop is None
    assert mgr.enable("pending") is True
    try:
        mgr.connect()
        assert mgr.server_status()["pending"] == "available"
    finally:
        mgr.close()


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


def test_close_submission_rejection_with_alive_loop_does_not_fabricate_completion(
    monkeypatch,
):
    mgr = MCPManager({}, shutdown_timeout=0.01, thread_join_timeout=0.01)
    loop = asyncio.new_event_loop()
    thread = threading.Thread(
        target=loop.run_forever,
        name="forgeagent-mcp-loop",
        daemon=True,
    )
    loop_blocked = threading.Event()
    release_loop = threading.Event()
    submitted = []

    def block_loop() -> None:
        loop_blocked.set()
        release_loop.wait()

    def reject(coro, submitted_loop):
        submitted.append(coro)
        assert submitted_loop is loop
        raise RuntimeError("submission rejected")

    mgr._loop = loop
    mgr._thread = thread
    mgr._started = True
    thread.start()
    loop.call_soon_threadsafe(block_loop)
    assert loop_blocked.wait(timeout=1)
    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", reject)

    try:
        assert mgr.close() is None

        assert submitted and submitted[0].cr_frame is None
        assert not mgr._shutdown_complete.is_set()
        assert mgr._shutdown_task is None
        assert mgr._loop is loop
        assert mgr._thread is thread

        release_loop.set()
        assert mgr._shutdown_complete.wait(timeout=1)
        thread.join(timeout=1)
        assert not thread.is_alive()
        assert mgr._shutdown_task is not None

        assert mgr.close() is None
        assert loop.is_closed()
        assert mgr._loop is None
        assert mgr._thread is None
    finally:
        release_loop.set()
        if thread.is_alive():
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=1)
        if not loop.is_closed():
            loop.close()


def test_close_submission_control_exception_survives_fallback_cleanup_error(monkeypatch):
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        shutdown_timeout=0.03,
        thread_join_timeout=0.02,
    )
    primary = KeyboardInterrupt()
    mgr._loop = _LoopProbe()
    mgr._thread = _ThreadProbe(alive=True)
    mgr._holders["pending"] = (1, object(), object())

    def reject(coro, submitted_loop):
        assert submitted_loop is mgr._loop
        raise primary

    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", reject)
    monkeypatch.setattr(
        mgr,
        "_request_shutdown_retry",
        lambda deadline: (_ for _ in ()).throw(SystemExit(9)),
    )

    try:
        with pytest.raises(KeyboardInterrupt) as raised:
            mgr.close()

        assert raised.value is primary
    finally:
        primary.__traceback__ = None
        mgr._holders.clear()
        mgr._loop = None
        mgr._thread = None


@pytest.mark.parametrize(
    "cleanup",
    [KeyboardInterrupt("facade cleanup secret"), SystemExit("facade cleanup secret")],
)
def test_close_submission_error_propagates_facade_cleanup_control_exception(
    monkeypatch,
    caplog,
    cleanup,
):
    mgr = MCPManager({}, shutdown_timeout=0.03, thread_join_timeout=0.02)
    primary = RuntimeError("submission secret")
    loop = _LoopProbe()
    thread = _ThreadProbe(alive=True, alive_results=[True, False])
    shutdown_coro = _CloseProbe(cleanup)
    retry_calls = []
    mgr._loop = loop
    mgr._thread = thread

    def reject(coro, submitted_loop):
        assert coro is shutdown_coro
        assert submitted_loop is loop
        raise primary

    monkeypatch.setattr(mgr, "_wait_for_shutdown", lambda deadline: shutdown_coro)
    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", reject)
    monkeypatch.setattr(mgr, "_request_shutdown_retry", retry_calls.append)
    caplog.set_level(logging.WARNING, logger="forgeagent.mcp_manager")

    try:
        with pytest.raises(type(cleanup)) as raised:
            mgr.close()

        assert raised.value is cleanup
        assert shutdown_coro.close_calls == 1
        assert len(retry_calls) == 2
        assert len(thread.join_timeouts) == 1
        assert not mgr._shutdown_complete.is_set()
        assert mgr._loop is loop
        assert mgr._thread is thread
        assert "MCP shutdown facade cleanup failed: " + type(cleanup).__name__ in caplog.text
        assert "submission secret" not in caplog.text
        assert "facade cleanup secret" not in caplog.text
    finally:
        primary.__traceback__ = None
        cleanup.__traceback__ = None
        mgr._loop = None
        mgr._thread = None


@pytest.mark.parametrize(
    ("primary", "cleanup"),
    [
        (KeyboardInterrupt("primary secret"), SystemExit("facade cleanup secret")),
        (KeyboardInterrupt("primary secret"), RuntimeError("facade cleanup secret")),
        (SystemExit("primary secret"), KeyboardInterrupt("facade cleanup secret")),
        (SystemExit("primary secret"), RuntimeError("facade cleanup secret")),
    ],
)
def test_close_submission_control_exception_remains_authoritative_over_facade_cleanup(
    monkeypatch,
    caplog,
    primary,
    cleanup,
):
    mgr = MCPManager({}, shutdown_timeout=0.03, thread_join_timeout=0.02)
    loop = _LoopProbe()
    thread = _ThreadProbe(alive=True, alive_results=[True, False])
    shutdown_coro = _CloseProbe(cleanup)
    retry_calls = []
    mgr._loop = loop
    mgr._thread = thread

    def reject(coro, submitted_loop):
        assert coro is shutdown_coro
        assert submitted_loop is loop
        raise primary

    monkeypatch.setattr(mgr, "_wait_for_shutdown", lambda deadline: shutdown_coro)
    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", reject)
    monkeypatch.setattr(mgr, "_request_shutdown_retry", retry_calls.append)
    caplog.set_level(logging.WARNING, logger="forgeagent.mcp_manager")

    try:
        with pytest.raises(type(primary)) as raised:
            mgr.close()

        assert raised.value is primary
        assert shutdown_coro.close_calls == 1
        assert len(retry_calls) == 2
        assert len(thread.join_timeouts) == 1
        assert "MCP shutdown facade cleanup failed: " + type(cleanup).__name__ in caplog.text
        assert "primary secret" not in caplog.text
        assert "facade cleanup secret" not in caplog.text
    finally:
        primary.__traceback__ = None
        cleanup.__traceback__ = None
        mgr._loop = None
        mgr._thread = None


def test_close_submission_and_facade_cleanup_errors_remain_public_no_throw(
    monkeypatch,
    caplog,
):
    mgr = MCPManager({}, shutdown_timeout=0.03, thread_join_timeout=0.02)
    primary = RuntimeError("submission secret")
    cleanup = OSError("facade cleanup secret")
    loop = _LoopProbe()
    thread = _ThreadProbe(alive=True, alive_results=[True, False])
    shutdown_coro = _CloseProbe(cleanup)
    retry_calls = []
    mgr._loop = loop
    mgr._thread = thread

    def reject(coro, submitted_loop):
        assert coro is shutdown_coro
        assert submitted_loop is loop
        raise primary

    monkeypatch.setattr(mgr, "_wait_for_shutdown", lambda deadline: shutdown_coro)
    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", reject)
    monkeypatch.setattr(mgr, "_request_shutdown_retry", retry_calls.append)
    caplog.set_level(logging.WARNING, logger="forgeagent.mcp_manager")

    try:
        assert mgr.close() is None

        assert shutdown_coro.close_calls == 1
        assert len(retry_calls) == 1
        assert len(thread.join_timeouts) == 1
        assert not mgr._shutdown_complete.is_set()
        assert mgr._loop is loop
        assert mgr._thread is thread
        assert "MCP shutdown facade cleanup failed: OSError" in caplog.text
        assert "MCP shutdown failed: RuntimeError" in caplog.text
        assert "submission secret" not in caplog.text
        assert "facade cleanup secret" not in caplog.text
    finally:
        primary.__traceback__ = None
        cleanup.__traceback__ = None
        mgr._loop = None
        mgr._thread = None


@pytest.mark.parametrize(
    "fallback",
    [KeyboardInterrupt("fallback secret"), SystemExit("fallback secret")],
)
def test_close_submission_error_propagates_fallback_control_exception(
    monkeypatch,
    caplog,
    fallback,
):
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        shutdown_timeout=0.03,
        thread_join_timeout=0.02,
    )
    primary = RuntimeError("submission secret")
    loop = _LoopProbe()
    thread = _ThreadProbe(alive=True, alive_results=[True, False])
    holder_slot = (1, object(), object())
    session_slot = (1, object())
    submitted = []
    fallback_calls = 0
    mgr._loop = loop
    mgr._thread = thread
    mgr._holders["pending"] = holder_slot
    mgr._sessions["pending"] = session_slot

    def reject(coro, submitted_loop):
        submitted.append(coro)
        assert submitted_loop is loop
        raise primary

    def fail_fallback(deadline):
        nonlocal fallback_calls
        fallback_calls += 1
        if fallback_calls == 1:
            raise fallback
        raise RuntimeError("secondary cleanup secret")

    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", reject)
    monkeypatch.setattr(mgr, "_request_shutdown_retry", fail_fallback)
    caplog.set_level(logging.WARNING, logger="forgeagent.mcp_manager")

    try:
        with pytest.raises(type(fallback)) as raised:
            mgr.close()

        assert raised.value is fallback
        assert submitted and submitted[0].cr_frame is None
        assert fallback_calls == 2
        assert len(thread.join_timeouts) == 1
        assert not mgr._shutdown_complete.is_set()
        assert mgr._holders == {"pending": holder_slot}
        assert mgr._sessions == {"pending": session_slot}
        assert mgr._loop is loop
        assert mgr._thread is thread
        assert "submission secret" not in caplog.text
        assert "fallback secret" not in caplog.text
        assert "secondary cleanup secret" not in caplog.text
    finally:
        primary.__traceback__ = None
        fallback.__traceback__ = None
        mgr._holders.clear()
        mgr._sessions.clear()
        mgr._loop = None
        mgr._thread = None


def test_close_submission_and_fallback_errors_remain_public_no_throw(monkeypatch, caplog):
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        shutdown_timeout=0.03,
        thread_join_timeout=0.02,
    )
    primary = RuntimeError("submission secret")
    fallback = OSError("fallback secret")
    loop = _LoopProbe()
    thread = _ThreadProbe(alive=True, alive_results=[True, False])
    holder_slot = (1, object(), object())
    session_slot = (1, object())
    submitted = []
    mgr._loop = loop
    mgr._thread = thread
    mgr._holders["pending"] = holder_slot
    mgr._sessions["pending"] = session_slot

    def reject(coro, submitted_loop):
        submitted.append(coro)
        assert submitted_loop is loop
        raise primary

    def fail_fallback(deadline):
        raise fallback

    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", reject)
    monkeypatch.setattr(mgr, "_request_shutdown_retry", fail_fallback)
    caplog.set_level(logging.WARNING, logger="forgeagent.mcp_manager")

    try:
        assert mgr.close() is None

        assert submitted and submitted[0].cr_frame is None
        assert len(thread.join_timeouts) == 1
        assert not mgr._shutdown_complete.is_set()
        assert mgr._holders == {"pending": holder_slot}
        assert mgr._sessions == {"pending": session_slot}
        assert mgr._loop is loop
        assert mgr._thread is thread
        assert "MCP shutdown fallback cleanup failed: OSError" in caplog.text
        assert "MCP shutdown failed: RuntimeError" in caplog.text
        assert "submission secret" not in caplog.text
        assert "fallback secret" not in caplog.text
    finally:
        primary.__traceback__ = None
        fallback.__traceback__ = None
        mgr._holders.clear()
        mgr._sessions.clear()
        mgr._loop = None
        mgr._thread = None


def test_close_on_already_closed_loop_has_no_unawaited_coroutine_warning():
    mgr = MCPManager({}, shutdown_timeout=0.03, thread_join_timeout=0.02)
    loop = asyncio.new_event_loop()
    loop.close()
    mgr._loop = loop
    mgr._thread = _ThreadProbe(alive=False)
    mgr._shutdown_complete.set()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert mgr.close() is None
        gc.collect()

    assert mgr._loop is None
    assert mgr._thread is None
    assert not any("never awaited" in str(item.message) for item in caught)


def test_close_dead_thread_with_empty_maps_does_not_synthesize_completion(monkeypatch, caplog):
    mgr = MCPManager({}, shutdown_timeout=0.03, thread_join_timeout=0.02)
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    mgr._loop = loop
    mgr._thread = thread
    thread.start()
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=1)
    assert not thread.is_alive()
    pending_facade = _FutureProbe()
    mgr._shutdown_future = pending_facade
    mgr._closed = True
    submissions = 0

    def reject_submission(coro, submitted_loop):
        nonlocal submissions
        submissions += 1
        coro.close()
        raise AssertionError("dead loop must not receive shutdown work")

    monkeypatch.setattr(
        mcp_manager_module.asyncio,
        "run_coroutine_threadsafe",
        reject_submission,
    )
    caplog.set_level(logging.WARNING, logger="forgeagent.mcp_manager")

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert mgr.close() is None
            gc.collect()

        assert submissions == 0
        assert not mgr._shutdown_complete.is_set()
        assert mgr._shutdown_future is pending_facade
        assert mgr._loop is loop
        assert mgr._thread is thread
        assert "shutdown incomplete; resources may remain" in caplog.text
        assert not any("never awaited" in str(item.message) for item in caught)
    finally:
        if not loop.is_closed():
            loop.close()


def test_close_dead_thread_retains_incomplete_resources_without_submission(monkeypatch, caplog):
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        shutdown_timeout=0.03,
        thread_join_timeout=0.02,
    )
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    stop = asyncio.Event()
    holder = loop.create_task(asyncio.sleep(3600))
    holder_slot = (1, holder, stop)
    session = object()
    session_slot = (1, session)
    submissions = 0
    mgr._loop = loop
    mgr._thread = thread
    mgr._holders["pending"] = holder_slot
    mgr._sessions["pending"] = session_slot

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
        assert mgr._holders == {"pending": holder_slot}
        assert mgr._sessions == {"pending": session_slot}
        assert mgr._loop is loop
        assert mgr._thread is thread
        assert "alive=False" in caplog.text
        assert "pending=['pending']" in caplog.text
        assert "shutdown incomplete; resources may remain" in caplog.text
    finally:
        mgr._holders.clear()
        mgr._sessions.clear()
        holder.cancel()
        loop.run_until_complete(asyncio.gather(holder, return_exceptions=True))
        loop.close()


def test_close_dead_thread_retains_pending_lifecycle_evidence(caplog):
    mgr = MCPManager({}, shutdown_timeout=0.03, thread_join_timeout=0.02)
    loop = asyncio.new_event_loop()
    lifecycle_task = loop.create_task(asyncio.sleep(3600))
    thread = _ThreadProbe(alive=False)
    mgr._loop = loop
    mgr._thread = thread
    mgr._lifecycle_tasks.add(lifecycle_task)
    caplog.set_level(logging.WARNING, logger="forgeagent.mcp_manager")

    try:
        assert mgr.close() is None

        assert not mgr._shutdown_complete.is_set()
        assert mgr._lifecycle_tasks == {lifecycle_task}
        assert mgr._loop is loop
        assert mgr._thread is thread
        assert "shutdown incomplete; resources may remain" in caplog.text
    finally:
        mgr._lifecycle_tasks.clear()
        lifecycle_task.cancel()
        loop.run_until_complete(asyncio.gather(lifecycle_task, return_exceptions=True))
        loop.close()


def test_close_consumes_shutdown_completion_that_arrives_during_join(monkeypatch):
    mgr = MCPManager({}, shutdown_timeout=0.0, thread_join_timeout=0.02)
    loop = _LoopProbe()

    class CompletingThread(_ThreadProbe):
        def join(self, timeout: float) -> None:
            super().join(timeout)
            mgr._shutdown_complete.set()
            self.alive = False

    thread = CompletingThread(alive=True)
    mgr._closed = True
    mgr._loop = loop
    mgr._thread = thread
    mgr._shutdown_future = _FutureProbe()
    monkeypatch.setattr(mgr, "_request_shutdown_retry", lambda deadline: None)

    assert mgr.close() is None

    assert mgr._shutdown_complete.is_set()
    assert loop.close_calls == 1
    assert mgr._shutdown_future is None
    assert mgr._loop is None
    assert mgr._thread is None


def test_close_retains_resources_when_loop_close_fails_and_retries(monkeypatch, caplog):
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
    holder_slot = (1, object(), object())
    session_slot = (1, object())
    mgr._loop = loop
    mgr._thread = thread
    mgr._holders["pending"] = holder_slot
    mgr._sessions["pending"] = session_slot
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
    assert mgr._shutdown_future is future
    assert mgr._holders == {"pending": holder_slot}
    assert mgr._sessions == {"pending": session_slot}
    assert mgr._loop is loop
    assert mgr._thread is thread
    assert "MCP shutdown failed: RuntimeError" in caplog.text
    assert "MCP loop stop failed: RuntimeError" in caplog.text
    assert "MCP loop thread join failed: RuntimeError" in caplog.text
    assert "MCP loop close failed: OSError" in caplog.text
    assert secret not in caplog.text

    loop._stop_error = None
    loop._close_error = None
    thread._join_error = None
    assert mgr.close() is None

    assert loop.close_calls == 2
    assert mgr._shutdown_future is None
    assert mgr._holders == {}
    assert mgr._sessions == {}
    assert mgr._loop is None
    assert mgr._thread is None


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


@pytest.mark.parametrize("control", [KeyboardInterrupt("cancel"), SystemExit("cancel")])
def test_close_runs_retry_and_join_before_propagating_cancel_control(monkeypatch, control):
    manager = MCPManager({}, shutdown_timeout=0.03, thread_join_timeout=0.02)
    manager._loop = _LoopProbe()
    manager._thread = _ThreadProbe(alive=True)
    future = _FutureProbe(error=RuntimeError("ordinary shutdown failure"))
    calls: list[str] = []

    def cancel():
        calls.append("cancel")
        raise control

    future.cancel = cancel
    monkeypatch.setattr(
        mcp_manager_module.asyncio,
        "run_coroutine_threadsafe",
        lambda coro, loop: (coro.close(), future)[1],
    )
    monkeypatch.setattr(manager, "_request_shutdown_retry", lambda deadline: calls.append("retry"))
    monkeypatch.setattr(
        manager,
        "_stop_and_join",
        lambda deadline, pending: calls.append("stop-and-join"),
    )

    with pytest.raises(type(control)) as raised:
        manager.close()

    assert raised.value is control
    assert calls == ["cancel", "retry", "stop-and-join"]


@pytest.mark.parametrize(
    ("primary", "secondary"),
    [
        (KeyboardInterrupt("primary"), SystemExit("secondary")),
        (SystemExit("primary"), KeyboardInterrupt("secondary")),
    ],
)
def test_close_control_primary_still_runs_retry_and_join_after_cancel_control(
    monkeypatch, primary, secondary
):
    manager = MCPManager({}, shutdown_timeout=0.03, thread_join_timeout=0.02)
    manager._loop = _LoopProbe()
    manager._thread = _ThreadProbe(alive=True)
    future = _FutureProbe(error=primary)
    calls: list[str] = []

    def cancel():
        calls.append("cancel")
        raise secondary

    future.cancel = cancel
    monkeypatch.setattr(
        mcp_manager_module.asyncio,
        "run_coroutine_threadsafe",
        lambda coro, loop: (coro.close(), future)[1],
    )
    monkeypatch.setattr(manager, "_request_shutdown_retry", lambda deadline: calls.append("retry"))
    monkeypatch.setattr(
        manager,
        "_stop_and_join",
        lambda deadline, pending: calls.append("stop-and-join"),
    )

    with pytest.raises(type(primary)) as raised:
        manager.close()

    assert raised.value is primary
    assert calls == ["cancel", "retry", "stop-and-join"]


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
        mgr._states["pending"].generation = 1
        mgr._states["pending"].status = "available"
        session = object()
        mgr._sessions["pending"] = (1, session)

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
                if mgr._sessions.get("pending") == (1, session):
                    mgr._sessions.pop("pending", None)
                cleanup_finished.set()

        mgr._holders["pending"] = (1, asyncio.create_task(holder()), stop)
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


def test_timed_out_disable_then_close_leaves_no_lifecycle_waiter(monkeypatch):
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        connect_timeout=-4.98,
        shutdown_timeout=0.03,
        thread_join_timeout=0.02,
    )
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    cleanup_started = threading.Event()
    submitted_futures: list[concurrent.futures.Future] = []
    loop_state: dict[str, asyncio.Event] = {}
    mgr._loop = loop
    mgr._thread = thread
    thread.start()

    async def install_holder() -> None:
        stop = asyncio.Event()
        cleanup_release = asyncio.Event()
        loop_state["cleanup_release"] = cleanup_release
        mgr._states["pending"].generation = 1
        mgr._states["pending"].status = "available"
        mgr._sessions["pending"] = (1, object())

        async def holder() -> None:
            try:
                await stop.wait()
            finally:
                cleanup_started.set()
                await cleanup_release.wait()

        mgr._holders["pending"] = (1, asyncio.create_task(holder()), stop)

    original_submit = asyncio.run_coroutine_threadsafe
    original_submit(install_holder(), loop).result(timeout=1)

    def submit(coro, submitted_loop):
        future = original_submit(coro, submitted_loop)
        submitted_futures.append(future)
        return future

    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", submit)

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with pytest.raises(concurrent.futures.TimeoutError):
                mgr.disable("pending")

            assert cleanup_started.wait(timeout=1)
            disable_future = submitted_futures[0]
            deadline = time.monotonic() + 0.5
            while not disable_future.cancelled() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert disable_future.cancelled()

            loop.call_soon_threadsafe(loop_state["cleanup_release"].set)
            holder = mgr._holders["pending"][1]
            deadline = time.monotonic() + 0.5
            while not holder.done() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert holder.done()
            assert mgr.close() is None
            thread.join(timeout=1)
            assert not thread.is_alive()
            assert mgr.close() is None
            gc.collect()

        assert not any(isinstance(item.message, RuntimeWarning) for item in caught)
    finally:
        if "cleanup_release" in loop_state and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(loop_state["cleanup_release"].set)
            except RuntimeError:
                pass
        if thread.is_alive():
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=1)
        if not loop.is_closed():
            loop.close()


def test_enable_during_timed_out_disable_restarts_after_old_holder_cleanup():
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        connect_timeout=-4.98,
    )
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    cleanup_started = threading.Event()
    replacement_started = threading.Event()
    loop_state: dict[str, asyncio.Event] = {}
    mgr._loop = loop
    mgr._thread = thread
    thread.start()

    async def replacement_holder(
        name: str,
        generation: int,
        ready: asyncio.Event,
        stop: asyncio.Event,
    ) -> None:
        mgr._states[name].status = "available"
        mgr._sessions[name] = (generation, object())
        ready.set()
        replacement_started.set()
        try:
            await stop.wait()
        finally:
            if mgr._sessions.get(name, (None,))[0] == generation:
                mgr._sessions.pop(name, None)

    mgr._holder = replacement_holder

    async def install_old_holder() -> None:
        stop = asyncio.Event()
        cleanup_release = asyncio.Event()
        loop_state["cleanup_release"] = cleanup_release
        mgr._states["pending"].generation = 1
        mgr._states["pending"].status = "available"
        session = object()
        mgr._sessions["pending"] = (1, session)

        async def old_holder() -> None:
            try:
                await stop.wait()
            finally:
                cleanup_started.set()
                await cleanup_release.wait()
                if mgr._sessions.get("pending") == (1, session):
                    mgr._sessions.pop("pending", None)

        task = asyncio.create_task(old_holder())
        mgr._holders["pending"] = (1, task, stop)
        task.add_done_callback(lambda done: mgr._finalize_holder_slot("pending", 1, done))
        await asyncio.sleep(0)

    asyncio.run_coroutine_threadsafe(install_old_holder(), loop).result(timeout=1)
    old_holder = mgr._holders["pending"]

    try:
        with pytest.raises(concurrent.futures.TimeoutError):
            mgr.disable("pending")
        assert cleanup_started.wait(timeout=1)
        assert mgr.enable("pending") is True

        loop.call_soon_threadsafe(loop_state["cleanup_release"].set)
        assert replacement_started.wait(timeout=0.5)
        assert mgr._holders["pending"] is not old_holder
        assert mgr._states["pending"].config.enabled is True
        assert mgr._states["pending"].status == "available"
        assert "pending" in mgr._sessions
    finally:
        mgr.close()
        if thread.is_alive():
            loop.call_soon_threadsafe(loop_state["cleanup_release"].set)
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=1)
        if not loop.is_closed():
            loop.close()


def test_multiple_hung_initial_holders_share_ready_deadline(monkeypatch):
    mgr = MCPManager(
        {
            "one": MCPServerConfig(command="unused"),
            "two": MCPServerConfig(command="unused"),
            "three": MCPServerConfig(command="unused"),
        },
        connect_timeout=0.05,
    )

    def hung_holder(name: str) -> asyncio.Event:
        mgr._states[name].generation += 1
        return asyncio.Event()

    mgr._start_holder = hung_holder

    waiters_started = 0
    all_waiters_started = asyncio.Event()

    async def concurrent_timeout(awaitable, timeout):
        nonlocal waiters_started
        waiters_started += 1
        if waiters_started == 3:
            all_waiters_started.set()
        await all_waiters_started.wait()
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(mcp_manager_module.asyncio, "wait_for", concurrent_timeout)
    asyncio.run(mgr._start_holders(["one", "two", "three"]))

    assert waiters_started == 3
    assert mgr.server_status() == {
        "one": "unavailable: connect timeout",
        "two": "unavailable: connect timeout",
        "three": "unavailable: connect timeout",
    }


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(7), asyncio.CancelledError()])
def test_start_holder_creation_base_exception_isolated_unavailable(monkeypatch, error):
    mgr = MCPManager({"pending": MCPServerConfig(command="unused")})
    closed = False

    class HolderCoroutine:
        def close(self):
            nonlocal closed
            closed = True

    monkeypatch.setattr(mgr, "_holder", lambda *args: HolderCoroutine())
    monkeypatch.setattr(
        mcp_manager_module.asyncio,
        "create_task",
        lambda coro: (_ for _ in ()).throw(error),
    )

    ready = mgr._start_holder("pending")

    assert ready.is_set()
    assert closed is True
    assert mgr._holders == {}
    assert mgr.server_status()["pending"] == f"unavailable: {type(error).__name__}"
    error.__traceback__ = None


def test_ready_publish_cannot_be_overwritten_by_timeout(monkeypatch):
    mgr = MCPManager({"pending": MCPServerConfig(command="unused")}, connect_timeout=0.01)

    async def fake_wait_for(awaitable, timeout: float):
        await awaitable
        raise TimeoutError

    async def run_startup() -> None:
        stop = asyncio.Event()

        async def holder() -> None:
            await stop.wait()

        def ready_holder(name: str) -> asyncio.Event:
            mgr._states[name].generation += 1
            generation = mgr._states[name].generation
            ready = asyncio.Event()
            task = asyncio.create_task(holder())
            mgr._holders[name] = (generation, task, stop)
            mgr._states[name].status = "available"
            mgr._sessions[name] = (generation, object())
            ready.set()
            return ready

        mgr._start_holder = ready_holder
        await mgr._start_holders(["pending"])
        stop.set()
        await asyncio.gather(*(slot[1] for slot in mgr._holders.values()))

    monkeypatch.setattr(mcp_manager_module.asyncio, "wait_for", fake_wait_for)

    asyncio.run(run_startup())

    assert mgr.server_status()["pending"] == "available"
    assert "pending" in mgr._sessions


def test_holder_task_creation_and_cleanup_errors_remain_fixed_unavailable(
    monkeypatch,
    caplog,
):
    mgr = MCPManager({"pending": MCPServerConfig(command="unused")})
    creation_error = RuntimeError("create task secret")
    cleanup_error = OSError("cleanup secret")
    caplog.set_level(logging.WARNING, logger="forgeagent.mcp_manager")

    async def run_startup_failure() -> asyncio.Event:
        closed = False

        class HolderCoroutine:
            def close(self) -> None:
                nonlocal closed
                closed = True
                raise cleanup_error

        monkeypatch.setattr(mgr, "_holder", lambda *args: HolderCoroutine())

        def reject_create_task(coro):
            raise creation_error

        monkeypatch.setattr(mcp_manager_module.asyncio, "create_task", reject_create_task)
        ready = mgr._start_holder("pending")
        assert closed is True
        return ready

    ready = asyncio.run(run_startup_failure())

    assert ready.is_set()
    assert mgr._holders == {}
    assert mgr.server_status()["pending"] == "unavailable: RuntimeError"
    assert "MCP holder coroutine cleanup failed: OSError" in caplog.text
    assert "create task secret" not in caplog.text
    assert "cleanup secret" not in caplog.text
    creation_error.__traceback__ = None
    cleanup_error.__traceback__ = None


def test_close_first_does_not_allocate_holder_generation(monkeypatch):
    mgr = MCPManager({"pending": MCPServerConfig(command="unused")})
    mgr.close()

    async def holder(
        name: str,
        generation: int,
        ready: asyncio.Event,
        stop: asyncio.Event,
    ) -> None:
        await stop.wait()

    monkeypatch.setattr(mgr, "_holder", holder)

    async def attempt_start() -> None:
        ready = mgr._start_holder("pending")
        try:
            assert ready.is_set()
            assert mgr._states["pending"].generation == 0
            assert mgr._holders == {}
        finally:
            slots = list(mgr._holders.values())
            for _generation, task, stop in slots:
                stop.set()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(attempt_start())


def test_close_racing_holder_task_creation_observes_fully_published_slot(monkeypatch):
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        shutdown_timeout=0.01,
        thread_join_timeout=0.01,
    )
    mgr._loop = _LoopProbe()
    mgr._thread = _ThreadProbe(alive=True)
    original_create_task = asyncio.create_task
    original_monotonic = time.monotonic
    create_task_entered = threading.Event()
    close_started = threading.Event()
    close_published = threading.Event()
    close_observations = []
    created_tasks = []
    closer: threading.Thread | None = None

    async def holder(
        name: str,
        generation: int,
        ready: asyncio.Event,
        stop: asyncio.Event,
    ) -> None:
        await stop.wait()

    def blocking_create_task(coro):
        task = original_create_task(coro)
        created_tasks.append(task)
        create_task_entered.set()
        assert close_started.wait(timeout=1)
        close_published.wait(timeout=0.05)
        return task

    def observed_monotonic() -> float:
        if closer is not None and threading.current_thread() is closer:
            if not close_published.is_set():
                close_observations.append(
                    (mgr._states["pending"].generation, mgr._holders.get("pending"))
                )
                close_published.set()
        return original_monotonic()

    def submit(coro, submitted_loop):
        assert submitted_loop is mgr._loop
        coro.close()
        return _FutureProbe()

    monkeypatch.setattr(mgr, "_holder", holder)
    monkeypatch.setattr(mcp_manager_module.asyncio, "create_task", blocking_create_task)
    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", submit)
    monkeypatch.setattr(mcp_manager_module.time, "monotonic", observed_monotonic)

    async def run_race() -> None:
        nonlocal closer

        def close_manager() -> None:
            assert create_task_entered.wait(timeout=1)
            close_started.set()
            mgr.close()

        closer = threading.Thread(target=close_manager)
        closer.start()
        ready = mgr._start_holder("pending")
        closer.join(timeout=1)

        assert not closer.is_alive()
        assert not ready.is_set()
        assert close_observations
        generation, observed_slot = close_observations[0]
        assert generation == 1
        assert observed_slot is not None
        assert observed_slot[0] == generation
        assert observed_slot[1] is created_tasks[0]
        assert mgr._holders["pending"] == observed_slot
        assert created_tasks[0]._callbacks is not None
        assert len(created_tasks[0]._callbacks) == 1

        _generation, task, stop = observed_slot
        stop.set()
        await asyncio.gather(task, return_exceptions=True)

    try:
        asyncio.run(run_race())
    finally:
        if closer is not None and closer.is_alive():
            closer.join(timeout=1)
        mgr._holders.clear()
        mgr._loop = None
        mgr._thread = None


def test_re_enable_old_holder_finally_does_not_delete_replacement_session():
    mgr = MCPManager({"pending": MCPServerConfig(command="unused")}, call_timeout=0.05)
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    mgr._loop = loop
    mgr._thread = thread
    thread.start()

    async def install_replacement_and_run_stale_finalizer() -> asyncio.Event:
        old_task = asyncio.create_task(asyncio.sleep(0))
        await asyncio.sleep(0)
        replacement_stop = asyncio.Event()
        replacement_task = asyncio.create_task(_park_until(replacement_stop))
        mgr._states["pending"].generation = 2
        mgr._states["pending"].status = "available"
        mgr._states["pending"].tools = [_tool()]
        mgr._sessions["pending"] = (2, _SessionProbe("replacement: ok"))
        mgr._holders["pending"] = (2, replacement_task, replacement_stop)
        mgr._finalize_holder_slot("pending", 1, old_task)
        return replacement_stop

    try:
        asyncio.run_coroutine_threadsafe(
            install_replacement_and_run_stale_finalizer(), loop
        ).result(timeout=1)

        assert mgr.server_status()["pending"] == "available"
        assert {tool.server for tool in mgr.list_tools()} == {"pending"}
        assert mgr.call_tool("pending", "echo", {"text": "x"})["text"] == "replacement: ok"
    finally:
        mgr.close()
        if thread.is_alive():
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=1)
        if not loop.is_closed():
            loop.close()


def test_call_failure_does_not_invalidate_replacement_session():
    mgr = MCPManager({"pending": MCPServerConfig(command="unused")}, call_timeout=0.05)
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    mgr._loop = loop
    mgr._thread = thread
    thread.start()

    old_stop_holder: dict[str, asyncio.Event] = {}
    replacement_session = _SessionProbe("replacement: ok")

    async def install_old_generation() -> None:
        old_stop = asyncio.Event()
        old_stop_holder["stop"] = old_stop
        old_task = asyncio.create_task(_park_until(old_stop))
        mgr._states["pending"].generation = 1
        mgr._states["pending"].status = "available"
        mgr._states["pending"].tools = [_tool()]
        mgr._holders["pending"] = (1, old_task, old_stop)

        def install_replacement_before_failure() -> None:
            old_stop.set()
            replacement_stop = asyncio.Event()
            replacement_task = asyncio.create_task(_park_until(replacement_stop))
            mgr._states["pending"].generation = 2
            mgr._states["pending"].status = "available"
            mgr._states["pending"].tools = [_tool()]
            mgr._holders["pending"] = (2, replacement_task, replacement_stop)
            mgr._sessions["pending"] = (2, replacement_session)

        failing_session = _SessionProbe(
            "old",
            error=RuntimeError("old generation failed"),
            before_error=install_replacement_before_failure,
        )
        mgr._sessions["pending"] = (1, failing_session)

    try:
        asyncio.run_coroutine_threadsafe(install_old_generation(), loop).result(timeout=1)

        result = mgr.call_tool("pending", "echo", {"text": "boom"})

        assert result["ok"] is False
        assert mgr.server_status()["pending"] == "available"
        assert {tool.server for tool in mgr.list_tools()} == {"pending"}
        assert mgr.call_tool("pending", "echo", {"text": "x"})["text"] == "replacement: ok"
        assert replacement_session.call_count == 1
    finally:
        if "stop" in old_stop_holder:
            loop.call_soon_threadsafe(old_stop_holder["stop"].set)
        mgr.close()
        if thread.is_alive():
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=1)
        if not loop.is_closed():
            loop.close()


def test_call_selection_occurs_on_loop_for_current_generation(monkeypatch):
    mgr = MCPManager({"pending": MCPServerConfig(command="unused")}, call_timeout=0.05)
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    mgr._loop = loop
    mgr._thread = thread
    thread.start()
    old_session = _SessionProbe("old")
    new_session = _SessionProbe("new")

    async def install_old_generation() -> asyncio.Event:
        old_stop = asyncio.Event()
        old_task = asyncio.create_task(_park_until(old_stop))
        mgr._states["pending"].generation = 1
        mgr._states["pending"].status = "available"
        mgr._states["pending"].tools = [_tool()]
        mgr._holders["pending"] = (1, old_task, old_stop)
        mgr._sessions["pending"] = (1, old_session)
        return old_stop

    old_stop = asyncio.run_coroutine_threadsafe(install_old_generation(), loop).result(timeout=1)
    original_submit = mgr._submit

    def submit_after_replacement(coro, timeout: float, *, cancel_on_timeout: bool = True):
        assert cancel_on_timeout is False

        async def swap_then_run():
            old_stop.set()
            replacement_stop = asyncio.Event()
            replacement_task = asyncio.create_task(_park_until(replacement_stop))
            mgr._states["pending"].generation = 2
            mgr._states["pending"].status = "available"
            mgr._states["pending"].tools = [_tool()]
            mgr._holders["pending"] = (2, replacement_task, replacement_stop)
            mgr._sessions["pending"] = (2, new_session)
            return await coro

        return original_submit(
            swap_then_run(),
            timeout,
            cancel_on_timeout=cancel_on_timeout,
        )

    monkeypatch.setattr(mgr, "_submit", submit_after_replacement)

    try:
        result = mgr.call_tool("pending", "echo", {"text": "x"})

        assert result == {"ok": True, "text": "new"}
        assert old_session.call_count == 0
        assert new_session.thread_ids == [thread.ident]
    finally:
        mgr.close()
        if thread.is_alive():
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=1)
        if not loop.is_closed():
            loop.close()


@pytest.mark.parametrize(
    ("state_generation", "holder_generation", "session_generation"),
    [(2, 1, 1), (2, 1, 2), (2, 2, 1)],
)
def test_call_requires_matching_state_holder_and_session_generations(
    state_generation, holder_generation, session_generation
):
    mgr = MCPManager({"pending": MCPServerConfig(command="unused")})
    session = _SessionProbe("must not run")

    async def call_with_mismatched_ownership() -> None:
        stop = asyncio.Event()
        holder = asyncio.create_task(_park_until(stop))
        mgr._states["pending"].generation = state_generation
        mgr._states["pending"].status = "available"
        mgr._states["pending"].tools = [_tool()]
        mgr._holders["pending"] = (holder_generation, holder, stop)
        mgr._sessions["pending"] = (session_generation, session)
        try:
            result = await mgr._call_tool_on_loop("pending", "echo", {})
            assert result["ok"] is False
            assert session.call_count == 0
        finally:
            stop.set()
            await asyncio.gather(holder, return_exceptions=True)

    asyncio.run(call_with_mismatched_ownership())


def test_active_call_failure_finalizes_without_implicit_restart(monkeypatch):
    mgr = MCPManager({"pending": MCPServerConfig(command="unused")})
    mgr._secret_values = {"ordinary detail secret"}

    async def fail_active_call() -> None:
        async def holder(
            name: str,
            generation: int,
            ready: asyncio.Event,
            stop: asyncio.Event,
        ) -> None:
            ready.set()
            await stop.wait()

        monkeypatch.setattr(mgr, "_holder", holder)
        ready = mgr._start_holder("pending")
        await ready.wait()
        generation, holder_task, stop = mgr._holders["pending"]
        mgr._states["pending"].status = "available"
        mgr._states["pending"].tools = [_tool()]
        mgr._sessions["pending"] = (
            generation,
            _SessionProbe("failed", error=RuntimeError("ordinary detail secret")),
        )

        result = await mgr._call_tool_on_loop("pending", "echo", {})

        assert result == {
            "ok": False,
            "text": "MCP call failed: RuntimeError: ***REDACTED***",
        }
        assert mgr._states["pending"].tearing_down_generation == generation
        assert mgr._states["pending"].restart_after_generation is None
        assert stop.is_set()
        await asyncio.gather(holder_task, return_exceptions=True)
        await asyncio.sleep(0)
        assert mgr._states["pending"].generation == generation
        assert mgr._states["pending"].tearing_down_generation is None
        assert mgr._states["pending"].restart_after_generation is None
        assert mgr.server_status()["pending"] == "unavailable: RuntimeError"
        assert mgr._holders == {}
        assert mgr._sessions == {}
        assert mgr.list_tools() == []

    asyncio.run(fail_active_call())


def test_call_tool_on_loop_preserves_cancellation():
    mgr = MCPManager({"pending": MCPServerConfig(command="unused")})

    async def cancel_call() -> None:
        stop = asyncio.Event()
        holder = asyncio.create_task(_park_until(stop))
        state = mgr._states["pending"]
        state.generation = 1
        state.status = "available"
        state.tools = [_tool()]
        session = _SessionProbe("unused", error=asyncio.CancelledError())
        mgr._holders["pending"] = (1, holder, stop)
        mgr._sessions["pending"] = (1, session)
        try:
            with pytest.raises(asyncio.CancelledError):
                await mgr._call_tool_on_loop("pending", "echo", {})
            assert mgr.server_status()["pending"] == "available"
            assert mgr._sessions["pending"] == (1, session)
            assert stop.is_set() is False
        finally:
            stop.set()
            await holder

    asyncio.run(cancel_call())


@pytest.mark.parametrize(
    "control",
    [KeyboardInterrupt("SDK control secret"), SystemExit("SDK control secret")],
)
def test_call_tool_isolates_sdk_control_on_real_loop(monkeypatch, control):
    mgr = MCPManager(
        {"pending": MCPServerConfig(command="unused")},
        call_timeout=-4.95,
        shutdown_timeout=0.03,
        thread_join_timeout=0.02,
    )
    loop = asyncio.new_event_loop()
    loop_messages = []
    loop.set_exception_handler(lambda _loop, context: loop_messages.append(context["message"]))
    thread = threading.Thread(
        target=loop.run_forever,
        name="forgeagent-mcp-loop",
        daemon=True,
    )
    mgr._loop = loop
    mgr._thread = thread
    mgr._started = True
    holder_starts = []
    holder_observations = []
    callback_ran = threading.Event()

    async def holder(
        name: str,
        generation: int,
        ready: asyncio.Event,
        stop: asyncio.Event,
    ) -> None:
        holder_starts.append(generation)
        ready.set()
        await stop.wait()
        state = mgr._states[name]
        holder_observations.append(
            {
                "generation": generation,
                "tearing_down": state.tearing_down_generation,
                "restart_after": state.restart_after_generation,
                "status": state.status,
                "session_present": name in mgr._sessions,
                "tools": list(state.tools),
            }
        )

    monkeypatch.setattr(mgr, "_holder", holder)
    original_submit = asyncio.run_coroutine_threadsafe
    result = None
    generation = None
    loop_survived = False
    holder_finalized = False
    close_error = None

    async def install_current_generation() -> int:
        ready = mgr._start_holder("pending")
        await ready.wait()
        state = mgr._states["pending"]
        state.status = "available"
        state.tools = [_tool()]
        mgr._sessions["pending"] = (
            state.generation,
            _SessionProbe("unused", error=control),
        )
        return state.generation

    async def wait_for_holder_finalization() -> bool:
        for _ in range(20):
            if "pending" not in mgr._holders:
                return True
            await asyncio.sleep(0)
        return False

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        thread.start()
        generation = original_submit(install_current_generation(), loop).result(timeout=0.2)
        result = mgr.call_tool("pending", "echo", {})

        thread.join(timeout=0.02)
        loop_survived = thread.is_alive()
        if loop_survived:
            loop.call_soon_threadsafe(callback_ran.set)
            holder_finalized = original_submit(wait_for_holder_finalization(), loop).result(
                timeout=0.2
            )
            try:
                mgr.close()
            except BaseException as exc:
                close_error = exc
            thread.join(timeout=0.2)
        else:
            pending = list(asyncio.all_tasks(loop))
            for task in pending:
                task.cancel()
            mgr._holders.clear()
            mgr._sessions.clear()
            mgr._lifecycle_tasks.clear()
            mgr._loop = None
            mgr._thread = None
            loop.close()
            pending.clear()
        gc.collect()

    try:
        assert result == {
            "ok": False,
            "text": f"MCP call failed: {type(control).__name__}",
        }
        assert "SDK control secret" not in result["text"]
        assert loop_survived is True
        assert callback_ran.wait(timeout=0.2)
        assert holder_finalized is True
        assert holder_starts == [generation]
        assert holder_observations == [
            {
                "generation": generation,
                "tearing_down": generation,
                "restart_after": None,
                "status": f"unavailable: {type(control).__name__}",
                "session_present": False,
                "tools": [],
            }
        ]
        state = mgr._states["pending"]
        assert state.generation == generation
        assert state.tearing_down_generation is None
        assert state.restart_after_generation is None
        assert mgr.server_status()["pending"] == f"unavailable: {type(control).__name__}"
        assert mgr._holders == {}
        assert mgr._sessions == {}
        assert mgr.list_tools() == []
        assert loop_messages == []
        assert caught == []
        assert close_error is None
        assert not thread.is_alive()
        assert loop.is_closed()
    finally:
        control.__traceback__ = None
        if not loop.is_closed():
            loop.close()


def test_call_outer_timeout_returns_structured_failure_without_invalidating_session(monkeypatch):
    mgr = MCPManager({"pending": MCPServerConfig(command="unused")})
    session = _SessionProbe("still live")
    mgr._loop = object()
    mgr._states["pending"].status = "available"
    mgr._states["pending"].generation = 1
    mgr._sessions["pending"] = (1, session)

    future = _FutureProbe(error=concurrent.futures.TimeoutError())

    def timeout_submit(coro, loop):
        coro.close()
        return future

    monkeypatch.setattr(mcp_manager_module.asyncio, "run_coroutine_threadsafe", timeout_submit)

    result = mgr.call_tool("pending", "echo", {})

    assert result["ok"] is False
    assert "MCP call failed: TimeoutError" in result["text"]
    assert future.cancel_calls == 0
    assert mgr._sessions["pending"] == (1, session)


def test_enable_racing_failed_holder_finalizer_starts_one_replacement():
    mgr = MCPManager({"pending": MCPServerConfig(command="unused")}, connect_timeout=0.05)
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    starts: list[int] = []
    mgr._loop = loop
    mgr._thread = thread
    thread.start()

    async def replacement_holder(
        name: str,
        generation: int,
        ready: asyncio.Event,
        stop: asyncio.Event,
    ):
        starts.append(generation)
        mgr._states[name].status = "available"
        mgr._states[name].tools = [_tool(name)]
        mgr._sessions[name] = (generation, _SessionProbe(f"generation {generation}"))
        ready.set()
        await stop.wait()

    mgr._holder = replacement_holder

    async def install_failed_slot() -> None:
        stop = asyncio.Event()

        async def failed_holder() -> None:
            raise RuntimeError("holder failed")

        task = asyncio.create_task(failed_holder())
        await asyncio.sleep(0)
        task.exception()
        mgr._states["pending"].generation = 1
        mgr._states["pending"].status = "unavailable: RuntimeError"
        mgr._holders["pending"] = (1, task, stop)

    try:
        asyncio.run_coroutine_threadsafe(install_failed_slot(), loop).result(timeout=1)

        assert mgr.enable("pending") is True

        assert starts == [2]
        assert mgr.server_status()["pending"] == "available"
        assert mgr.call_tool("pending", "echo", {})["text"] == "generation 2"
    finally:
        mgr.close()
        if thread.is_alive():
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=1)
        if not loop.is_closed():
            loop.close()


def test_enable_after_failed_holder_finalized_starts_one_generation():
    mgr = MCPManager({"pending": MCPServerConfig(command="unused")}, connect_timeout=0.05)
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    starts: list[int] = []
    mgr._loop = loop
    mgr._thread = thread
    thread.start()
    mgr._states["pending"].generation = 3
    mgr._states["pending"].status = "unavailable: RuntimeError"

    async def replacement_holder(
        name: str,
        generation: int,
        ready: asyncio.Event,
        stop: asyncio.Event,
    ):
        starts.append(generation)
        mgr._states[name].status = "available"
        mgr._states[name].tools = [_tool(name)]
        mgr._sessions[name] = (generation, _SessionProbe(f"generation {generation}"))
        ready.set()
        await stop.wait()

    mgr._holder = replacement_holder

    try:
        assert mgr.enable("pending") is True
        assert mgr.enable("pending") is True

        assert starts == [4]
        assert mgr.server_status()["pending"] == "available"
        assert mgr.call_tool("pending", "echo", {})["text"] == "generation 4"
    finally:
        mgr.close()
        if thread.is_alive():
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=1)
        if not loop.is_closed():
            loop.close()


def test_disable_during_holder_initialization_never_publishes_available(monkeypatch):
    import mcp
    import mcp.client.stdio as mcp_stdio

    mgr = MCPManager({"pending": MCPServerConfig(command="unused")}, connect_timeout=0.2)
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    initialize_started = threading.Event()
    release_initialize = threading.Event()
    mgr._loop = loop
    mgr._thread = thread
    thread.start()

    class FakeTool:
        name = "echo"
        description = "Echo"
        inputSchema = {}

    class FakeToolList:
        tools = [FakeTool()]

    class FakeSession:
        def __init__(self, *args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def initialize(self):
            initialize_started.set()
            while not release_initialize.is_set():
                await asyncio.sleep(0.001)

        async def list_tools(self):
            return FakeToolList()

        def call_tool(self, tool: str, arguments: dict, *, read_timeout_seconds):
            async def run():
                return _CallResult("should not publish")

            return run()

    class FakeStdioClient:
        async def __aenter__(self):
            return object(), object()

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(mcp, "ClientSession", FakeSession)
    monkeypatch.setattr(mcp_stdio, "stdio_client", lambda params: FakeStdioClient())

    async def start_holder() -> asyncio.Event:
        return mgr._start_holder("pending")

    try:
        ready = asyncio.run_coroutine_threadsafe(start_holder(), loop).result(timeout=1)
        assert initialize_started.wait(timeout=1)

        disable_result: list[bool] = []
        disable_errors: list[BaseException] = []

        def disable() -> None:
            try:
                disable_result.append(mgr.disable("pending"))
            except BaseException as exc:  # surfaced below on the test thread
                disable_errors.append(exc)

        disable_thread = threading.Thread(target=disable)
        disable_thread.start()
        deadline = time.monotonic() + 1
        while mgr._states["pending"].config.enabled and time.monotonic() < deadline:
            time.sleep(0.001)
        assert mgr._states["pending"].config.enabled is False
        release_initialize.set()
        disable_thread.join(timeout=1)
        assert not disable_thread.is_alive()
        assert disable_errors == []
        assert disable_result == [True]
        asyncio.run_coroutine_threadsafe(ready.wait(), loop).result(timeout=1)

        assert mgr.server_status()["pending"] == "unavailable: disabled"
        assert mgr.list_tools() == []
        assert mgr.call_tool("pending", "echo", {})["ok"] is False
    finally:
        release_initialize.set()
        mgr.close()
        if thread.is_alive():
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
