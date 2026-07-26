"""Executor backends: run a code block and return a structured result.

See docs/threat-model.md (B2). The executor is an abstract backend interface; the
concrete backend is chosen by sandbox tier:
  - trusted    -> TrustedBackend (same-process exec, globals persist across blocks)
  - restricted -> per-block subprocess + app-layer limits  (M4)
  - container  -> container backend                          (M8)

TrustedBackend (M3) runs code in one persistent namespace so globals set by an earlier
block are visible to later ones (matches agent's in-process model), injects the
`utils` runtime, and captures stdout/stderr plus any exception.

RestrictedBackend (M4) runs each block in a fresh subprocess with a PEP 578 audit hook
(path whitelist + network deny) and rlimits, with a hard timeout (SIGKILL). Cross-block
state crosses the process boundary as JSON (never pickle — see _sandbox_worker). A
failing or killed block yields ExecResult(success=False), never crashing the host.

ContainerBackend (M8) runs each block in a one-shot `docker run` container: the same
worker/JSON protocol, but isolation is OS-level (mount namespace with only allowed_root
mounted, --network none, --pids-limit/--memory/--cpus, --cap-drop ALL, non-root,
read-only rootfs, /sys masked). The worker skips its audit hook there (os_isolated).
"""

from __future__ import annotations

import atexit
import io
import json
import shutil
import subprocess
import sys
import tempfile
import traceback
import uuid
from abc import ABC, abstractmethod
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from pydantic import BaseModel, Field

from .runtime import Runtime
from .secret_policy import mask_secrets, scrub_environment, sensitive_env_values


class ExecResult(BaseModel):
    """Structured outcome of executing one code block."""

    success: bool
    stdout: str = ""
    stderr: str = ""
    # Exception summary when success is False (type + message + traceback tail).
    error: str | None = None
    # Runtime.set_state keys this block set that could not cross the restricted
    # backend's process boundary (not JSON-serializable). Always empty for
    # TrustedBackend, which shares Runtime's state in-process. See _sandbox_worker's
    # _json_safe — the model needs to know a state key vanished, not just find it
    # missing in a later block with no explanation.
    dropped_state_keys: list[str] = Field(default_factory=list)


def _mask_result(result: ExecResult, secret_values: set[str]) -> ExecResult:
    """Redact secret values from a result's captured output before it leaves the backend
    (into the feedback loop / console). No-op when there is nothing to mask."""
    if not secret_values:
        return result
    return result.model_copy(
        update={
            "stdout": mask_secrets(result.stdout, secret_values),
            "stderr": mask_secrets(result.stderr, secret_values),
            "error": mask_secrets(result.error, secret_values) if result.error else result.error,
        }
    )


class ExecutorBackend(ABC):
    """Runs a code block against a shared runtime; returns a structured ExecResult."""

    @abstractmethod
    def execute(self, code: str, runtime: Runtime) -> ExecResult:
        """Execute `code`, exposing `utils` = runtime to it. Never raises for code
        errors — those are captured into ExecResult(success=False)."""


class TrustedBackend(ExecutorBackend):
    """Same-process backend. Globals persist across blocks within one task.

    NO isolation — trusted tier only (user opts in, self-owned risk). The persistent
    namespace is this backend's own dict, reused on every execute() call so variables
    defined by one block are available to the next.
    """

    def __init__(self, *, secret_values: set[str] | None = None) -> None:
        # One namespace shared across all blocks of the task this backend serves.
        self._namespace: dict = {"__name__": "__forgeagent_block__"}
        # Trusted tier cannot scrub os.environ (it shares the host process), so masking
        # secret values out of output is the only credential hygiene available here.
        self._secret_values = sensitive_env_values() if secret_values is None else secret_values

    def execute(self, code: str, runtime: Runtime) -> ExecResult:
        return _mask_result(self._run(code, runtime), self._secret_values)

    def _run(self, code: str, runtime: Runtime) -> ExecResult:
        # `utils` is refreshed each call so the block always sees the current runtime.
        self._namespace["utils"] = runtime
        out, err = io.StringIO(), io.StringIO()
        try:
            compiled = compile(code, "<forgeagent-block>", "exec")
        except SyntaxError as exc:
            return ExecResult(
                success=False,
                error=f"SyntaxError: {exc.msg} (line {exc.lineno})",
            )
        try:
            with redirect_stdout(out), redirect_stderr(err):
                exec(compiled, self._namespace)  # noqa: S102 - trusted tier, by design
        except BaseException as exc:  # noqa: BLE001 - capture everything, never crash host
            return ExecResult(
                success=False,
                stdout=out.getvalue(),
                stderr=err.getvalue(),
                error=_format_exception(exc),
            )
        return ExecResult(success=True, stdout=out.getvalue(), stderr=err.getvalue())


def _format_exception(exc: BaseException) -> str:
    """Render an exception into a readable single string for LLM feedback."""
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    # Keep the type/message line plus the tail of the traceback (drop our exec frame noise).
    return "".join(tb).strip()


def _parse_worker_frame(
    stdout: str, returncode: int, stderr: str, *, worker_label: str
) -> ExecResult | dict:
    """Decode a sandbox worker's JSON result frame, or an ExecResult describing why it
    couldn't be decoded. Shared by the restricted and container backends — both talk the
    same one-shot stdin/stdout worker protocol.

    The frame is UNTRUSTED: model code can write arbitrary bytes to the real stdout
    (sys.__stdout__) and os._exit(0) before the worker writes its own frame. Anything
    that is not a dict-shaped frame must come back as a structured failure, never as an
    exception out of execute()."""
    if returncode != 0 or not stdout:
        # Worker died before writing a result frame (e.g. rlimit kill, crash).
        return ExecResult(
            success=False,
            error=f"{worker_label} failed (exit {returncode}): {stderr.strip()[:500]}",
        )
    try:
        frame = json.loads(stdout)
    except json.JSONDecodeError:
        return ExecResult(
            success=False,
            error=f"{worker_label} produced invalid result: {stdout[:500]}",
        )
    if not isinstance(frame, dict) or not isinstance(frame.get("state", {}), dict):
        return ExecResult(
            success=False,
            error=f"{worker_label} produced a malformed result frame: {stdout[:500]}",
        )
    return frame


def _result_from_frame(frame: dict, state_store: dict, runtime: Runtime) -> ExecResult:
    """Persist the frame's returned state into the backend store + runtime, and build
    the ExecResult. Shared post-processing for both out-of-process backends."""
    state_store.clear()
    state_store.update(frame.get("state", {}))
    for key, value in state_store.items():
        runtime.set_state(key, value)
    return ExecResult(
        success=bool(frame.get("success", False)),
        stdout=str(frame.get("stdout", "")),
        stderr=str(frame.get("stderr", "")),
        error=frame.get("error"),
        dropped_state_keys=list(frame.get("dropped_state_keys", [])),
    )


class RestrictedBackend(ExecutorBackend):
    """Per-block subprocess backend with app-layer limits (restricted tier).

    Each execute() spawns a fresh `python -I -m forgeagent._sandbox_worker`, which uses
    isolated module resolution, then installs an audit hook (path whitelist + network
    deny) and rlimits before running the code.
    A hard timeout kills a runaway block (SIGKILL) without losing the main process's
    accumulated cross-block state. State crosses as JSON only.
    """

    def __init__(
        self,
        *,
        allowed_root: str | None = None,
        timeout_seconds: float = 30.0,
        cpu_seconds: int = 10,
        memory_mb: int = 512,
        secret_values: set[str] | None = None,
    ):
        # Default allowed root is the current working directory (the project/task dir).
        self._allowed_root = str(Path(allowed_root or Path.cwd()).resolve())
        self._timeout = timeout_seconds
        self._cpu_seconds = cpu_seconds
        self._memory_mb = memory_mb
        # Cross-block state held by the main process, injected into each subprocess.
        self._state: dict = {}
        # The subprocess is launched with a scrubbed env (secrets removed), so this
        # masking is only a backstop; captured once here for both purposes.
        self._secret_values = sensitive_env_values() if secret_values is None else secret_values

    def execute(self, code: str, runtime: Runtime) -> ExecResult:
        return _mask_result(self._run(code, runtime), self._secret_values)

    def _run(self, code: str, runtime: Runtime) -> ExecResult:
        # Seed this block's state from prior blocks (runtime state takes precedence).
        merged = {**self._state, **runtime.state}
        payload = json.dumps(
            {
                "code": code,
                "state": merged,
                "allowed_root": self._allowed_root,
                "cpu_seconds": self._cpu_seconds,
                "memory_mb": self._memory_mb,
            }
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-m", "forgeagent._sandbox_worker"],
                input=payload,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                # Prevention (T1): the child never sees the agent's own credentials, so
                # model code cannot read them via os.environ. Non-secret vars (PATH, ...)
                # are kept so the worker still starts and imports normally.
                env=scrub_environment(),
            )
        except subprocess.TimeoutExpired:
            # subprocess.run already SIGKILLs the child on timeout; prior state is intact.
            return ExecResult(
                success=False,
                error=f"execution timed out after {self._timeout}s (process killed)",
            )

        frame = _parse_worker_frame(
            proc.stdout, proc.returncode, proc.stderr, worker_label="sandbox worker"
        )
        if isinstance(frame, ExecResult):
            return frame
        # Persist returned state for later blocks and reflect it into the runtime.
        return _result_from_frame(frame, self._state, runtime)


class ContainerBackend(ExecutorBackend):
    """Per-block one-shot container backend (container tier, M8).

    Each execute() runs `docker run --rm -i` with the same one-shot JSON worker protocol
    as RestrictedBackend, but isolation is OS-level, not the audit hook (the worker is
    told os_isolated and skips it):

      - mount namespace: only allowed_root is mounted (rw, same path — no translation),
        so the rest of the host filesystem simply does not exist inside;
      - --network none: no network device at all (ctypes-level bypasses have no NIC);
      - --pids-limit / --memory / --cpus: hard OS-level resource limits;
      - --cap-drop ALL, no-new-privileges, non-root --user, read-only rootfs,
        --tmpfs /sys (masks host topology; docker's default /proc masks stay in place);
      - env is NOT inherited by docker run, so the agent's credentials never enter.

    Timeout: killing the docker CLI client does NOT kill the container (verified in the
    M8 spike, D4b) — on timeout we explicitly `docker kill` the named container.

    Requires a container runtime (docker CLI + running daemon). Constructing the backend
    verifies availability and raises ContainerRuntimeError otherwise — never a silent
    downgrade to a weaker tier.
    """

    def __init__(
        self,
        *,
        allowed_root: str | None = None,
        image: str = "python:3.11-slim",
        timeout_seconds: float = 60.0,
        memory_mb: int = 512,
        cpus: float = 1.0,
        pids_limit: int = 64,
        container_cli: str = "docker",
        secret_values: set[str] | None = None,
    ):
        self._allowed_root = str(Path(allowed_root or Path.cwd()).resolve())
        # A ':' in the mount path would be parsed by docker as the src:dst:mode
        # separator, silently mounting the wrong path. Refuse instead.
        if ":" in self._allowed_root:
            raise ContainerRuntimeError(
                f"allowed_root path contains ':' which docker -v cannot represent: "
                f"{self._allowed_root}"
            )
        self._image = image
        self._timeout = timeout_seconds
        self._memory_mb = memory_mb
        self._cpus = cpus
        self._pids_limit = pids_limit
        self._cli = container_cli
        self._state: dict = {}
        self._secret_values = sensitive_env_values() if secret_values is None else secret_values
        _verify_container_runtime(self._cli, self._image)
        # Minimal package skeleton mounted read-only into the container so
        # `python -m forgeagent._sandbox_worker` resolves there (worker + runtime are
        # stdlib-only, so the bare official image suffices — no custom image build).
        # atexit is the backstop for callers that never reach close() (e.g. a REPL
        # killed mid-task); close() itself is idempotent.
        self._skeleton_dir = _build_worker_skeleton()
        atexit.register(self.close)

    def close(self) -> None:
        """Remove the temporary worker-skeleton directory."""
        shutil.rmtree(self._skeleton_dir, ignore_errors=True)

    def execute(self, code: str, runtime: Runtime) -> ExecResult:
        return _mask_result(self._run(code, runtime), self._secret_values)

    def _run_command(self, container_name: str) -> list[str]:
        uid = os_uid_gid()
        cmd = [
            self._cli,
            "run",
            "--rm",
            "-i",
            "--name",
            container_name,
            "--network",
            "none",
            "--memory",
            f"{self._memory_mb}m",
            "--cpus",
            str(self._cpus),
            "--pids-limit",
            str(self._pids_limit),
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp",
            # T9b (M8 decision 9): mask host topology/cgroup details; /proc keeps
            # docker's default masks (runc forbids custom mounts inside /proc).
            "--tmpfs",
            "/sys:ro",
            "-v",
            f"{self._allowed_root}:{self._allowed_root}",
            "-v",
            f"{self._skeleton_dir}:/opt/fa:ro",
            "-e",
            "PYTHONPATH=/opt/fa",
            "-w",
            self._allowed_root,
        ]
        if uid is not None:
            cmd += ["--user", uid]
        cmd += [self._image, "python", "-m", "forgeagent._sandbox_worker"]
        return cmd

    def _run(self, code: str, runtime: Runtime) -> ExecResult:
        merged = {**self._state, **runtime.state}
        payload = json.dumps(
            {
                "code": code,
                "state": merged,
                "allowed_root": self._allowed_root,
                "os_isolated": True,
            }
        )
        container_name = f"forgeagent-{uuid.uuid4().hex[:12]}"
        try:
            proc = subprocess.run(
                self._run_command(container_name),
                input=payload,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except subprocess.TimeoutExpired:
            # Killing the docker CLI does not kill the container (spike D4b) — kill it
            # by name. Truly best-effort: a hung daemon (the likely cause of the
            # timeout) must not let TimeoutExpired escape execute().
            try:
                subprocess.run([self._cli, "kill", container_name], capture_output=True, timeout=10)
            except (subprocess.TimeoutExpired, OSError):
                pass
            return ExecResult(
                success=False,
                error=f"execution timed out after {self._timeout}s (container killed)",
            )
        frame = _parse_worker_frame(
            proc.stdout, proc.returncode, proc.stderr, worker_label="container worker"
        )
        if isinstance(frame, ExecResult):
            return frame
        return _result_from_frame(frame, self._state, runtime)


class ContainerRuntimeError(Exception):
    """The container runtime (docker) is unavailable or the image is missing."""


def os_uid_gid() -> str | None:
    """`uid:gid` of the current user for docker --user, or None on Windows (no getuid);
    file ownership of writes into the mounted allowed_root then matches the host user."""
    import os

    if not hasattr(os, "getuid"):
        return None
    return f"{os.getuid()}:{os.getgid()}"


def _verify_container_runtime(cli: str, image: str) -> None:
    """Fail fast (with a fix hint) when docker is absent, the daemon is down, or the
    image is not pulled. A missing runtime must be an error, not a silent downgrade to
    a weaker tier — tier IS the isolation strength (docs/threat-model.md)."""
    if shutil.which(cli) is None:
        raise ContainerRuntimeError(
            f"container tier requires the {cli!r} CLI, which is not installed "
            f"(or not on PATH). Install it, or use --tier restricted."
        )
    try:
        info = subprocess.run([cli, "info"], capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired as exc:
        raise ContainerRuntimeError(f"{cli} info timed out — is the daemon running?") from exc
    if info.returncode != 0:
        raise ContainerRuntimeError(
            f"the {cli} daemon is not running ({info.stderr.strip()[:200]}). "
            f"Start it, or use --tier restricted."
        )
    have = subprocess.run(
        [cli, "image", "inspect", image], capture_output=True, text=True, timeout=20
    )
    if have.returncode != 0:
        raise ContainerRuntimeError(
            f"container image {image!r} is not available locally. Pull it first: {cli} pull {image}"
        )


def _build_worker_skeleton() -> str:
    """Create a temp dir holding a minimal `forgeagent` package (worker + runtime only)
    to mount read-only into the container (spike D8). Both modules are stdlib-only, so
    the bare official python image can run them."""
    from . import _sandbox_worker
    from . import runtime as runtime_module

    skeleton = tempfile.mkdtemp(prefix="forgeagent-worker-")
    package_dir = Path(skeleton) / "forgeagent"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("")
    for module in (_sandbox_worker, runtime_module):
        source = Path(module.__file__)
        shutil.copy(source, package_dir / source.name)
    return skeleton
