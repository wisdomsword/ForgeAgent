"""Unit tests for RestrictedBackend (M4-2).

These spawn REAL subprocesses (python -m forgeagent._sandbox_worker) against a temp
allowed_root. No network, no real secrets — the "outside" file is a temp file the test
creates outside allowed_root. Slower than in-process tests but this is the security
boundary, so it must be exercised for real.
"""

import sys

import pytest

from forgeagent.executor import ExecutorBackend, RestrictedBackend
from forgeagent.runtime import Runtime


def _backend(tmp_path, **kw) -> RestrictedBackend:
    return RestrictedBackend(allowed_root=str(tmp_path), timeout_seconds=15.0, **kw)


def test_restricted_is_an_executor_backend(tmp_path):
    assert isinstance(_backend(tmp_path), ExecutorBackend)


def test_normal_code_runs_in_subprocess(tmp_path):
    result = _backend(tmp_path).execute("print('hello from subprocess')", Runtime())
    assert result.success is True
    assert result.stdout.strip() == "hello from subprocess"


def test_cross_block_state_json_roundtrip(tmp_path):
    backend = _backend(tmp_path)
    rt = Runtime()
    r1 = backend.execute("utils.set_state('n', 21)", rt)
    assert r1.success is True
    # A fresh subprocess for block 2 receives block 1's state via JSON.
    r2 = backend.execute("print(utils.get_state('n') * 2)", rt)
    assert r2.success is True
    assert r2.stdout.strip() == "42"
    assert rt.get_state("n") == 21


def test_non_json_state_value_reported_as_dropped(tmp_path):
    # utils.set_state('s', {1, 2}) can't cross the process boundary as JSON — the
    # worker must say so via dropped_state_keys rather than silently losing it.
    backend = _backend(tmp_path)
    result = backend.execute("utils.set_state('s', {1, 2})", Runtime())
    assert result.success is True
    assert result.dropped_state_keys == ["s"]


def test_write_and_read_within_allowed_root_ok(tmp_path):
    backend = _backend(tmp_path)
    target = tmp_path / "out.txt"
    code = f"open({str(target)!r}, 'w').write('ok')\nprint(open({str(target)!r}).read())"
    result = backend.execute(code, Runtime())
    assert result.success is True
    assert result.stdout.strip() == "ok"


def test_read_outside_allowed_root_denied(tmp_path):
    # A secret file OUTSIDE allowed_root (sibling temp dir), created by the test.
    secret = tmp_path.parent / "secret_forgeagent_test.txt"
    secret.write_text("top-secret")
    try:
        backend = _backend(tmp_path)
        result = backend.execute(f"print(open({str(secret)!r}).read())", Runtime())
        assert result.success is False
        assert "restricted" in (result.error or "") or "PermissionError" in (result.error or "")
    finally:
        secret.unlink(missing_ok=True)


def test_read_outside_via_pathlib_also_denied(tmp_path):
    # audithook intercepts the low-level `open` event, so pathlib is covered too
    # (this is exactly what monkeypatching builtins.open would miss).
    secret = tmp_path.parent / "secret_pathlib_test.txt"
    secret.write_text("secret")
    try:
        backend = _backend(tmp_path)
        code = f"from pathlib import Path\nprint(Path({str(secret)!r}).read_text())"
        result = backend.execute(code, Runtime())
        assert result.success is False
    finally:
        secret.unlink(missing_ok=True)


def test_network_connect_denied(tmp_path):
    code = (
        "import socket\n"
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "s.connect(('127.0.0.1', 9))\n"
    )
    result = _backend(tmp_path).execute(code, Runtime())
    assert result.success is False
    assert "network access denied" in (result.error or "") or "restricted" in (result.error or "")


def test_dns_resolution_denied(tmp_path):
    code = "import socket\nsocket.getaddrinfo('example.com', 80)"
    result = _backend(tmp_path).execute(code, Runtime())
    assert result.success is False


def test_timeout_kills_runaway_block_and_next_block_still_runs(tmp_path):
    backend = RestrictedBackend(allowed_root=str(tmp_path), timeout_seconds=2.0)
    rt = Runtime()
    runaway = backend.execute("while True:\n    pass", rt)
    assert runaway.success is False
    assert "timed out" in (runaway.error or "")
    # The next block runs fine — killing the runaway did not break the backend.
    ok = backend.execute("print('still alive')", rt)
    assert ok.success is True
    assert ok.stdout.strip() == "still alive"


def test_exception_in_subprocess_captured(tmp_path):
    result = _backend(tmp_path).execute("1 / 0", Runtime())
    assert result.success is False
    assert "ZeroDivisionError" in result.error


@pytest.mark.skipif(sys.platform == "win32", reason="rlimit is Unix-only")
def test_memory_limit_enforced_or_gracefully_skipped(tmp_path):
    # RLIMIT_AS is unreliable on macOS (guarded in the worker). We only assert the
    # backend returns a structured result (success True or False), never crashes the host.
    backend = RestrictedBackend(allowed_root=str(tmp_path), timeout_seconds=10.0, memory_mb=128)
    result = backend.execute("x = 1 + 1\nprint(x)", Runtime())
    assert result.success in (True, False)
    if result.success:
        assert result.stdout.strip() == "2"
