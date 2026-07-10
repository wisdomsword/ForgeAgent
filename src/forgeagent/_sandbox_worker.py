"""Subprocess sandbox worker for the restricted backend (M4-2).

Run as `python -m forgeagent._sandbox_worker`. Reads a JSON payload from stdin
({code, state, allowed_root, cpu_seconds, memory_mb}), installs a PEP 578 audit hook
(path whitelist + network deny) and rlimits, executes the code with `utils` = Runtime,
and writes a JSON result to stdout ({success, stdout, stderr, error, state}).

Security notes:
- The audit hook intercepts the low-level `open` event, so open/pathlib/io/os.open all
  hit it — broader than monkeypatching `open`. It allows paths under the Python install
  (sys.prefix/base_prefix, needed for imports) and the task's allowed_root; denies the
  rest (home-dir secrets, /etc, ...). Network `socket.*` events are denied by default.
- Cross-block state is JSON only: the main process must never unpickle the (untrusted)
  subprocess output, or a malicious __reduce__ would execute in the trusted parent.
"""

from __future__ import annotations

import io
import json
import os
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout

_BLOCKED_SOCKET_EVENTS = frozenset(
    {"socket.connect", "socket.getaddrinfo", "socket.bind", "socket.sendto"}
)

# Spawning a child process would escape the audit hook (the child does not inherit it),
# so a child could read/exfiltrate freely. Deny process spawn/exec entirely in restricted.
_BLOCKED_SPAWN_EVENTS = frozenset(
    {"subprocess.Popen", "os.system", "os.exec", "os.spawn", "os.posix_spawn"}
)


def _install_audit_hook(allowed_root: str) -> None:
    """Install a PEP 578 hook: file opens limited to allowed roots; network denied."""
    real_root = os.path.realpath(allowed_root)
    allowed = [
        real_root,
        os.path.realpath(sys.base_prefix),
        os.path.realpath(sys.prefix),
    ]

    def hook(event: str, args: tuple) -> None:
        if event == "open":
            path = args[0]
            if not isinstance(path, (str, bytes)):
                return
            p = os.fsdecode(path) if isinstance(path, bytes) else path
            rp = os.path.realpath(p)
            for base in allowed:
                if rp == base or rp.startswith(base + os.sep):
                    return
            raise PermissionError(
                f"restricted: file access outside allowed root denied: {p}"
            )
        elif event in _BLOCKED_SOCKET_EVENTS:
            raise PermissionError(f"restricted: network access denied ({event})")
        elif event in _BLOCKED_SPAWN_EVENTS:
            raise PermissionError(f"restricted: process spawn denied ({event})")

    sys.addaudithook(hook)


def _apply_rlimits(cpu_seconds: int, memory_mb: int) -> None:
    """Apply CPU/file-descriptor limits (Unix only). No-op where `resource` is absent
    (Windows) — the subprocess timeout in the parent is the cross-platform backstop."""
    try:
        import resource
    except ImportError:
        return  # Windows: rely on parent-side timeout only
    if cpu_seconds > 0:
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        except (ValueError, OSError):
            pass
    if memory_mb > 0 and hasattr(resource, "RLIMIT_AS"):
        # RLIMIT_AS is unreliable on macOS; guard so a failure never aborts the worker.
        try:
            limit = memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        except (ValueError, OSError):
            pass


def _json_safe(state: dict) -> tuple[dict, list[str]]:
    """Keep only JSON-serializable entries (state crosses the process boundary as JSON).

    Returns (safe_state, dropped_keys) so the caller can tell the model a state key
    silently vanished instead of leaving it to guess why a later block sees nothing.
    """
    safe: dict = {}
    dropped: list[str] = []
    for key, value in state.items():
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            dropped.append(key)
            continue
        safe[key] = value
    return safe, dropped


def main() -> None:
    payload = json.loads(sys.stdin.read())
    allowed_root = payload["allowed_root"]
    # Import runtime BEFORE installing the hook (its module file may live outside roots).
    from forgeagent.runtime import Runtime

    runtime = Runtime(state=dict(payload.get("state", {})))

    _apply_rlimits(payload.get("cpu_seconds", 0), payload.get("memory_mb", 0))
    _install_audit_hook(allowed_root)

    out, err = io.StringIO(), io.StringIO()
    result = {"success": True, "stdout": "", "stderr": "", "error": None, "state": {}}
    namespace: dict = {"__name__": "__forgeagent_block__", "utils": runtime}
    try:
        with redirect_stdout(out), redirect_stderr(err):
            exec(compile(payload["code"], "<forgeagent-block>", "exec"), namespace)  # noqa: S102
    except BaseException as exc:  # noqa: BLE001 - capture everything, report structured
        result["success"] = False
        result["error"] = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ).strip()
    result["stdout"] = out.getvalue()
    result["stderr"] = err.getvalue()
    safe_state, dropped_state_keys = _json_safe(runtime.state)
    result["state"] = safe_state
    result["dropped_state_keys"] = dropped_state_keys
    # The result frame goes to the real stdout (code stdout was captured above).
    sys.__stdout__.write(json.dumps(result))
    sys.__stdout__.flush()


if __name__ == "__main__":
    main()
