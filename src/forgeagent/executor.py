"""Executor backends: run a code block and return a structured result.

See docs/threat-model.md (B2). The executor is an abstract backend interface; the
concrete backend is chosen by sandbox tier:
  - trusted    -> TrustedBackend (same-process exec, globals persist across blocks)
  - restricted -> per-block subprocess + app-layer limits  (M4)
  - container  -> container backend                          (M10, tentative)

TrustedBackend (M3) runs code in one persistent namespace so globals set by an earlier
block are visible to later ones (matches agent's in-process model), injects the
`utils` runtime, and captures stdout/stderr plus any exception.

RestrictedBackend (M4) runs each block in a fresh subprocess with a PEP 578 audit hook
(path whitelist + network deny) and rlimits, with a hard timeout (SIGKILL). Cross-block
state crosses the process boundary as JSON (never pickle — see _sandbox_worker). A
failing or killed block yields ExecResult(success=False), never crashing the host.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import traceback
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


class RestrictedBackend(ExecutorBackend):
    """Per-block subprocess backend with app-layer limits (restricted tier).

    Each execute() spawns a fresh `python -m forgeagent._sandbox_worker`, which installs
    an audit hook (path whitelist + network deny) and rlimits before running the code.
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
                [sys.executable, "-m", "forgeagent._sandbox_worker"],
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

        if proc.returncode != 0 or not proc.stdout:
            # Worker died before writing a result frame (e.g. rlimit kill, crash).
            return ExecResult(
                success=False,
                error=f"sandbox worker failed (exit {proc.returncode}): "
                f"{proc.stderr.strip()[:500]}",
            )
        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return ExecResult(
                success=False,
                error=f"sandbox worker produced invalid result: {proc.stdout[:500]}",
            )
        # Persist returned state for later blocks and reflect it into the runtime.
        self._state = result.get("state", {})
        for key, value in self._state.items():
            runtime.set_state(key, value)
        return ExecResult(
            success=result["success"],
            stdout=result.get("stdout", ""),
            stderr=result.get("stderr", ""),
            error=result.get("error"),
            dropped_state_keys=result.get("dropped_state_keys", []),
        )
