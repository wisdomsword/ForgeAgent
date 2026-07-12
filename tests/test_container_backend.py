"""ContainerBackend tests (M8).

Two groups:
  - No-docker unit tests: command assembly, runtime-verification error paths (docker
    CLI mocked away) — always run.
  - Integration + escape tests: REAL `docker run` one-shot containers. Skipped when
    docker (or the image) is unavailable — "base CI runs without docker", mirroring
    the no-key principle for model clients. The escape group asserts the OS-level
    boundary: mounted-root-only visibility, no network device, pids limit, non-root,
    /sys masked (T1/T3/T6/T9 in container form — docs/m8-container-sandbox.md §四).
"""

import json
import shutil
import subprocess

import pytest

from forgeagent.executor import (
    ContainerBackend,
    ContainerRuntimeError,
    ExecutorBackend,
    _build_worker_skeleton,
)
from forgeagent.runtime import Runtime

IMAGE = "python:3.11-slim"


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        info = subprocess.run(["docker", "info"], capture_output=True, timeout=20)
        if info.returncode != 0:
            return False
        have = subprocess.run(
            ["docker", "image", "inspect", IMAGE], capture_output=True, timeout=20
        )
        return have.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


docker_required = pytest.mark.skipif(
    not _docker_ready(), reason=f"docker daemon or {IMAGE} image unavailable"
)


# --- no-docker unit tests ------------------------------------------------------


def test_missing_cli_raises_clear_error(tmp_path):
    with pytest.raises(ContainerRuntimeError, match="not installed"):
        ContainerBackend(allowed_root=str(tmp_path), container_cli="no-such-cli-xyz")


def test_worker_skeleton_contains_worker_and_runtime(tmp_path):
    skeleton = _build_worker_skeleton()
    try:
        package = list(p for p in __import__("pathlib").Path(skeleton).iterdir())[0]
        names = {f.name for f in package.iterdir()}
        assert names == {"__init__.py", "_sandbox_worker.py", "runtime.py"}
    finally:
        shutil.rmtree(skeleton, ignore_errors=True)


def test_allowed_root_with_colon_rejected(tmp_path, monkeypatch):
    import forgeagent.executor as executor_module

    monkeypatch.setattr(executor_module, "_verify_container_runtime", lambda cli, image: None)
    bad = tmp_path / "proj:v2"
    bad.mkdir()
    with pytest.raises(ContainerRuntimeError, match="':'"):
        ContainerBackend(allowed_root=str(bad))


def test_run_command_hardening_flags(tmp_path, monkeypatch):
    # Pure command-assembly check — docker itself is not needed, so the runtime probe
    # is stubbed out to keep this regression running on docker-less CI.
    import forgeagent.executor as executor_module

    monkeypatch.setattr(executor_module, "_verify_container_runtime", lambda cli, image: None)
    backend = ContainerBackend(allowed_root=str(tmp_path), timeout_seconds=30.0)
    try:
        cmd = backend._run_command("forgeagent-test")
        joined = " ".join(cmd)
        for flag in (
            "--network none", "--cap-drop ALL", "--read-only",
            "--security-opt no-new-privileges", "--tmpfs /sys:ro", "--pids-limit",
        ):
            assert flag in joined
        # allowed_root mounted at the SAME path (path transparency, decision 5).
        assert f"-v {tmp_path.resolve()}:{tmp_path.resolve()}" in joined
    finally:
        backend.close()


# --- integration: the worker protocol through a real container ------------------


@docker_required
def test_normal_code_runs_in_container(tmp_path):
    backend = ContainerBackend(allowed_root=str(tmp_path), timeout_seconds=60.0)
    try:
        assert isinstance(backend, ExecutorBackend)
        result = backend.execute("print('hello from container')", Runtime())
        assert result.success is True
        assert result.stdout.strip() == "hello from container"
    finally:
        backend.close()


@docker_required
def test_cross_block_state_roundtrip_through_containers(tmp_path):
    backend = ContainerBackend(allowed_root=str(tmp_path), timeout_seconds=60.0)
    rt = Runtime()
    try:
        r1 = backend.execute("utils.set_state('n', 21)", rt)
        assert r1.success is True
        r2 = backend.execute("print(utils.get_state('n') * 2)", rt)
        assert r2.success is True
        assert r2.stdout.strip() == "42"
    finally:
        backend.close()


@docker_required
def test_same_path_mount_read_write(tmp_path):
    (tmp_path / "in.txt").write_text("host-data")
    backend = ContainerBackend(allowed_root=str(tmp_path), timeout_seconds=60.0)
    try:
        code = (
            f"print(open({str(tmp_path / 'in.txt')!r}).read())\n"
            f"open({str(tmp_path / 'out.txt')!r}, 'w').write('from-container')"
        )
        result = backend.execute(code, Runtime())
        assert result.success is True
        assert "host-data" in result.stdout
        assert (tmp_path / "out.txt").read_text() == "from-container"
    finally:
        backend.close()


@docker_required
def test_timeout_kills_container_and_next_block_runs(tmp_path):
    backend = ContainerBackend(allowed_root=str(tmp_path), timeout_seconds=8.0)
    rt = Runtime()
    try:
        runaway = backend.execute("while True:\n    pass", rt)
        assert runaway.success is False
        assert "timed out" in (runaway.error or "")
        # No residual container. `--rm` removal after docker kill is asynchronous in
        # the daemon, so poll briefly instead of asserting a single snapshot.
        import time

        for _ in range(10):
            ps = subprocess.run(
                ["docker", "ps", "-a", "--filter", "name=forgeagent-",
                 "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=20,
            )
            if ps.stdout.strip() == "":
                break
            time.sleep(0.5)
        assert ps.stdout.strip() == ""
        ok = backend.execute("print('alive')", rt)
        assert ok.success is True
        assert ok.stdout.strip() == "alive"
    finally:
        backend.close()


@docker_required
def test_exception_in_container_captured(tmp_path):
    backend = ContainerBackend(allowed_root=str(tmp_path), timeout_seconds=60.0)
    try:
        result = backend.execute("1 / 0", Runtime())
        assert result.success is False
        assert "ZeroDivisionError" in (result.error or "")
    finally:
        backend.close()


# --- escape tests, container form (T1/T3/T6/T9) --------------------------------


@docker_required
def test_t1_host_filesystem_not_visible(tmp_path):
    # Stronger than restricted's "access denied": outside paths DO NOT EXIST inside
    # the mount namespace.
    secret = tmp_path.parent / "container_t1_secret.txt"
    secret.write_text("host-secret")
    backend = ContainerBackend(allowed_root=str(tmp_path), timeout_seconds=60.0)
    try:
        code = (
            "import os\n"
            f"print('exists:', os.path.exists({str(secret)!r}))\n"
            f"print('home:', os.path.exists(os.path.expanduser('~/.ssh')))"
        )
        result = backend.execute(code, Runtime())
        assert result.success is True
        assert "exists: False" in result.stdout
        assert "home: False" in result.stdout
    finally:
        backend.close()
        secret.unlink(missing_ok=True)


@docker_required
def test_t3_no_network_device(tmp_path):
    backend = ContainerBackend(allowed_root=str(tmp_path), timeout_seconds=60.0)
    try:
        code = (
            "import socket\n"
            "try:\n"
            "    socket.socket().connect(('1.1.1.1', 80))\n"
            "    print('CONNECTED')\n"
            "except OSError as e:\n"
            "    print('blocked:', e)\n"
        )
        result = backend.execute(code, Runtime())
        assert result.success is True
        assert "CONNECTED" not in result.stdout
        # Spike D5: --network none error shape, not restricted's 'denied' marker.
        assert "unreachable" in result.stdout.lower()
    finally:
        backend.close()


@docker_required
def test_t6_pids_limit_stops_fork_bomb(tmp_path):
    backend = ContainerBackend(allowed_root=str(tmp_path), timeout_seconds=60.0, pids_limit=16)
    try:
        code = (
            "import os\n"
            "count = 0\n"
            "try:\n"
            "    for _ in range(64):\n"
            "        if os.fork() == 0:\n"
            "            import time; time.sleep(3); os._exit(0)\n"
            "        count += 1\n"
            "    print('UNBOUNDED', count)\n"
            "except OSError:\n"
            "    print('capped at', count)\n"
        )
        result = backend.execute(code, Runtime())
        assert "UNBOUNDED" not in (result.stdout + (result.error or ""))
    finally:
        backend.close()


@docker_required
def test_t9_non_root_and_sys_masked(tmp_path):
    backend = ContainerBackend(allowed_root=str(tmp_path), timeout_seconds=60.0)
    try:
        code = (
            "import os\n"
            "print('uid:', os.getuid())\n"
            "print('sys:', os.listdir('/sys'))\n"
        )
        result = backend.execute(code, Runtime())
        assert result.success is True
        assert "uid: 0" not in result.stdout  # non-root
        assert "sys: []" in result.stdout  # /sys masked by tmpfs (decision 9 / T9b)
    finally:
        backend.close()


@docker_required
def test_t9_no_secret_env_inside_container(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_TEST_API_KEY", "sk-super-secret-value-123")
    backend = ContainerBackend(allowed_root=str(tmp_path), timeout_seconds=60.0)
    try:
        code = (
            "import os, json\n"
            "print(json.dumps({'has_key': 'FORGE_TEST_API_KEY' in os.environ,"
            " 'env_count': len(os.environ)}))"
        )
        result = backend.execute(code, Runtime())
        assert result.success is True
        data = json.loads(result.stdout)
        assert data["has_key"] is False  # docker run does not inherit host env
    finally:
        backend.close()
