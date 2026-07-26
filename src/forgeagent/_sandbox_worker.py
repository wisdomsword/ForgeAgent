"""Subprocess sandbox worker for the restricted backend (M4-2).

Run as `python -m forgeagent._sandbox_worker`. Reads a JSON payload from stdin
({code, state, allowed_root, cpu_seconds, memory_mb, os_isolated}), installs a PEP 578
audit hook (path whitelist + network deny) and rlimits, executes the code with
`utils` = Runtime, and writes a JSON result to stdout ({success, stdout, stderr, error,
state}).

When `os_isolated` is true (container tier) the audit hook and rlimits are SKIPPED:
isolation is provided by the container itself (mount namespace, --network none,
--pids-limit, --memory/--cpus), and the in-process hook would only produce false
positives (e.g. legitimate multiprocessing inside the container).

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

# Spawning a child process would escape the audit hook (the child does not inherit it),
# so a child could read/exfiltrate freely. Deny process spawn/exec entirely in restricted.
_BLOCKED_SPAWN_EVENTS = frozenset(
    {
        "subprocess.Popen",
        "os.system",
        "os.exec",
        "os.spawn",
        "os.posix_spawn",
        "os.fork",
        "os.forkpty",
    }
)
_BLOCKED_PROCESS_CONTROL_EVENTS = frozenset({"os.kill", "os.killpg"})
_PATH_MUTATION_EVENTS: dict[str, tuple[tuple[int, int | None], ...]] = {
    "os.chflags": ((0, None),),
    "os.chmod": ((0, 2),),
    "os.chown": ((0, 3),),
    "os.link": ((0, 2), (1, 3)),
    "os.mkdir": ((0, 2),),
    "os.remove": ((0, 1),),
    "os.removexattr": ((0, None),),
    "os.rename": ((0, 2), (1, 3)),
    "os.rmdir": ((0, 1),),
    "os.setxattr": ((0, None),),
    "os.symlink": ((1, 2),),
    "os.truncate": ((0, None),),
    "os.utime": ((0, 3),),
}


def _install_audit_hook(
    allowed_root: str,
    *,
    writes_only_in_root: bool = False,
    readable_directory_roots: tuple[str, ...] = (),
    allowed_files: tuple[str, ...] = (),
) -> None:
    """Install a PEP 578 hook: file opens limited to allowed roots; network denied."""
    real_root = os.path.realpath(allowed_root)
    allowed = [
        real_root,
        os.path.realpath(sys.base_prefix),
        os.path.realpath(sys.prefix),
    ]
    readable_directories = [
        real_root,
        *(os.path.realpath(root) for root in readable_directory_roots),
    ]
    allowed_file_paths = {os.path.realpath(path) for path in allowed_files}

    def hook(event: str, args: tuple) -> None:
        if event == "open":
            path = args[0]
            if not isinstance(path, (str, bytes)):
                return
            p = os.fsdecode(path) if isinstance(path, bytes) else path
            try:
                rp = os.path.realpath(p)
            except ValueError:
                raise PermissionError(
                    "restricted: file access outside allowed root denied"
                ) from None
            write_access = _open_requests_write(args)
            if rp in allowed_file_paths:
                return
            permitted = [real_root] if writes_only_in_root and write_access else allowed
            for base in permitted:
                try:
                    common = os.path.commonpath((base, rp))
                except ValueError:
                    continue
                if os.path.normcase(common) == os.path.normcase(base):
                    return
            raise PermissionError("restricted: file access outside allowed root denied")
        elif event.startswith("socket."):
            raise PermissionError(f"restricted: network access denied ({event})")
        elif event in _BLOCKED_SPAWN_EVENTS:
            raise PermissionError(f"restricted: process spawn denied ({event})")
        elif event in _BLOCKED_PROCESS_CONTROL_EVENTS:
            raise PermissionError(f"restricted: process control denied ({event})")
        elif event == "os.chdir":
            path = args[0]
            if not isinstance(path, int) and not _audit_path_within_root(path, -1, real_root):
                raise PermissionError("restricted: file access outside allowed root denied")
        elif event in {"os.listdir", "os.scandir"}:
            path = args[0]
            if not isinstance(path, int) and not any(
                _audit_path_within_root(path, -1, root) for root in readable_directories
            ):
                raise PermissionError("restricted: file access outside allowed root denied")
        elif path_specs := _PATH_MUTATION_EVENTS.get(event):
            for path_index, dir_fd_index in path_specs:
                path = args[path_index]
                if isinstance(path, int):
                    continue
                dir_fd = args[dir_fd_index] if dir_fd_index is not None else -1
                if not _audit_path_within_root(path, dir_fd, real_root):
                    raise PermissionError("restricted: file mutation outside allowed root denied")

    sys.addaudithook(hook)


def _open_requests_write(args: tuple) -> bool:
    mode = args[1] if len(args) > 1 else None
    if isinstance(mode, str) and any(character in mode for character in "wax+"):
        return True
    flags = args[2] if len(args) > 2 else 0
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
    return isinstance(flags, int) and bool(flags & write_flags)


def _audit_path_within_root(path: str | bytes | None, dir_fd: int, real_root: str) -> bool:
    decoded = os.curdir if path is None else os.fsdecode(path) if isinstance(path, bytes) else path
    if not os.path.isabs(decoded):
        if dir_fd in {-1, None}:
            base = os.getcwd()
        else:
            base = os.path.realpath(f"/dev/fd/{dir_fd}")
            if not os.path.isabs(base):
                return False
        decoded = os.path.join(base, decoded)
    try:
        resolved = os.path.realpath(decoded)
        common = os.path.commonpath((real_root, resolved))
    except (OSError, ValueError):
        return False
    return os.path.normcase(common) == os.path.normcase(real_root)


def _apply_rlimits(cpu_seconds: int, memory_mb: int) -> None:
    """Apply CPU and address-space limits (Unix only). No-op where `resource` is absent
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

    if not payload.get("os_isolated", False):
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
        if isinstance(exc, PermissionError) and str(exc).startswith("restricted:"):
            result["error"] = str(exc)
        else:
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
