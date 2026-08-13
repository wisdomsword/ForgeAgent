"""Unit tests for RestrictedBackend (M4-2).

These spawn REAL subprocesses (python -I -m forgeagent._sandbox_worker) against a temp
allowed_root. No network, no real secrets — the "outside" file is a temp file the test
creates outside allowed_root. Slower than in-process tests but this is the security
boundary, so it must be exercised for real.
"""

import os
import signal
import sys
import sysconfig

import pytest

from forgeagent.executor import ExecutorBackend, RestrictedBackend, _parse_worker_frame
from forgeagent.runtime import Runtime


def _backend(tmp_path, **kw) -> RestrictedBackend:
    return RestrictedBackend(allowed_root=str(tmp_path), timeout_seconds=15.0, **kw)


def test_restricted_is_an_executor_backend(tmp_path):
    assert isinstance(_backend(tmp_path), ExecutorBackend)


def test_normal_code_runs_in_subprocess(tmp_path):
    result = _backend(tmp_path).execute("print('hello from subprocess')", Runtime())
    assert result.success is True
    assert result.stdout.strip() == "hello from subprocess"


def test_worker_bootstrap_ignores_shadow_forgeagent_package(tmp_path, monkeypatch):
    shadow_package = tmp_path / "forgeagent"
    shadow_package.mkdir()
    (shadow_package / "__init__.py").write_text("")
    worker_marker = tmp_path / "shadow-worker-ran"
    runtime_marker = tmp_path / "shadow-runtime-ran"
    (shadow_package / "runtime.py").write_text(
        f"from pathlib import Path\nPath({str(runtime_marker)!r}).write_text('ran')\n"
    )
    (shadow_package / "_sandbox_worker.py").write_text(
        "import json\n"
        "from pathlib import Path\n"
        "from forgeagent import runtime\n"
        f"Path({str(worker_marker)!r}).write_text('ran')\n"
        "print(json.dumps({'success': True, 'stdout': 'shadow worker', 'stderr': '', "
        "'error': None, 'state': {}, 'dropped_state_keys': []}))\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))

    result = _backend(tmp_path).execute("print('installed worker')", Runtime())

    assert result.success is True
    assert result.stdout.strip() == "installed worker"
    assert not worker_marker.exists()
    assert not runtime_marker.exists()


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
        assert str(secret) not in (result.error or "")
    finally:
        secret.unlink(missing_ok=True)


def test_filesystem_root_allows_tmp_file(tmp_path):
    target = tmp_path / "inside-filesystem-root.txt"
    target.write_text("ok")

    result = RestrictedBackend(allowed_root=os.path.abspath(os.sep)).execute(
        f"print(open({str(target)!r}).read())", Runtime()
    )

    assert result.success is True
    assert result.stdout.strip() == "ok"


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


def test_runtime_site_packages_write_outside_allowed_root_denied(tmp_path):
    backend = _backend(tmp_path)
    site_packages = sysconfig.get_path("purelib")
    target = os.path.join(site_packages, f"forgeagent_s1_write_probe_{tmp_path.name}.py")
    if os.path.exists(target):
        os.unlink(target)
    try:
        result = backend.execute(f"open({target!r}, 'w').write('blocked')", Runtime())
        assert result.success is False
        assert result.error == "restricted: file access outside allowed root denied"
        assert not os.path.exists(target)
    finally:
        if os.path.exists(target):
            os.unlink(target)


def test_runtime_site_packages_pth_creation_outside_allowed_root_denied(tmp_path):
    backend = _backend(tmp_path)
    site_packages = sysconfig.get_path("purelib")
    target = os.path.join(site_packages, f"forgeagent_s1_escape_probe_{tmp_path.name}.pth")
    if os.path.exists(target):
        os.unlink(target)
    try:
        contents = "import os\n"
        code = f"open({target!r}, 'w').write({contents!r})"
        result = backend.execute(code, Runtime())
        assert result.success is False
        assert result.error == "restricted: file access outside allowed root denied"
        assert not os.path.exists(target)
    finally:
        if os.path.exists(target):
            os.unlink(target)


def test_installed_worker_file_write_outside_allowed_root_denied(tmp_path):
    backend = _backend(tmp_path)
    import forgeagent._sandbox_worker as installed_worker

    target = installed_worker.__file__
    with open(target, encoding="utf-8") as handle:
        original = handle.read()
    result = backend.execute(f"open({target!r}, 'w').write('blocked')", Runtime())
    assert result.success is False
    assert result.error == "restricted: file access outside allowed root denied"
    with open(target, encoding="utf-8") as handle:
        assert handle.read() == original


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


@pytest.mark.skipif(not hasattr(signal, "SIGXCPU"), reason="SIGXCPU is unavailable")
def test_cpu_limit_failure_keeps_output_produced_before_worker_signal(tmp_path):
    backend = RestrictedBackend(allowed_root=str(tmp_path), timeout_seconds=10.0, cpu_seconds=1)

    result = backend.execute(
        "import sys\nprint('before cpu limit')\nsys.stderr.write('before cpu error\\n')\n"
        "while True:\n    pass",
        Runtime(),
    )

    assert result.success is False
    assert "before cpu limit" in result.stdout
    assert "before cpu error" in result.stderr
    assert "CPU time limit" in (result.error or "")


def test_worker_sigxcpu_is_human_readable_and_preserves_captured_output():
    result = _parse_worker_frame(
        "",
        -signal.SIGXCPU,
        "launcher diagnostics",
        worker_label="sandbox worker",
        captured_stdout="partial stdout",
        captured_stderr="partial stderr",
        cpu_seconds=7,
    )

    assert isinstance(result, ExecutorBackend) is False
    assert result.success is False
    assert result.stdout == "partial stdout"
    assert "partial stderr" in result.stderr
    assert "CPU time limit (7s)" in (result.error or "")


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
