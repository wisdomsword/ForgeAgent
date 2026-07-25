"""Run host-defined evaluator checks against a disposable project copy."""

from __future__ import annotations

import os
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .secret_policy import is_secret_name, mask_audit_data, sensitive_env_values

_OUTPUT_LIMIT = 16 * 1024
_POLL_SECONDS = 0.01
_IGNORED_NAMES = {
    ".git",
    ".forgeagent",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}
_ENV_ALLOWLIST = {"LANG", "LC_ALL", "PATH", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR"}
CheckStatus = Literal["passed", "failed", "timeout", "cancelled", "copy_error", "start_error"]


class CheckDefinition(BaseModel):
    """A trusted, server-owned command exposed to the evaluator by identifier."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    argv: tuple[str, ...] = Field(min_length=1)
    timeout_seconds: float = Field(default=60.0, ge=0.01, le=3600.0)
    env: dict[str, str] = Field(default_factory=dict)

    @field_validator("argv")
    @classmethod
    def _validate_argv(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item or "\x00" in item for item in value):
            raise ValueError("argv entries must be non-empty and contain no NUL bytes")
        return value

    @field_validator("env")
    @classmethod
    def _validate_env(cls, value: dict[str, str]) -> dict[str, str]:
        for name, item in value.items():
            if not name or "\x00" in name or "=" in name or "\x00" in item:
                raise ValueError("invalid check environment entry")
            if is_secret_name(name):
                raise ValueError("check environment must not contain credentials")
        return dict(value)


class CheckResult(BaseModel):
    """Bounded, sanitized result returned to the evaluator."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    status: CheckStatus
    exit_code: int | None = None
    duration_ms: int = 0
    stdout: str = ""
    stderr: str = ""


def run_check(
    definition: CheckDefinition,
    *,
    allowed_root: str | Path,
    cancel_event: threading.Event | None = None,
) -> CheckResult:
    """Execute one fixed check without giving the evaluator a command surface."""
    started = time.monotonic()
    secrets = sensitive_env_values()
    if cancel_event is not None and cancel_event.is_set():
        return _result("cancelled", started, secrets=secrets)
    try:
        source_root = Path(allowed_root).resolve()
        _validate_source_tree(source_root)
    except (OSError, ValueError) as exc:
        return _result("copy_error", started, stderr=str(exc), secrets=secrets)

    with tempfile.TemporaryDirectory(prefix="forgeagent-check-") as temporary_root:
        working_root = Path(temporary_root) / "project"
        try:
            shutil.copytree(
                source_root,
                working_root,
                symlinks=True,
                ignore=_ignore_entries,
            )
        except (OSError, shutil.Error) as exc:
            return _result("copy_error", started, stderr=str(exc), secrets=secrets)

        environment = {
            name: value for name, value in os.environ.items() if name in _ENV_ALLOWLIST
        }
        environment.update(definition.env)
        environment["TMPDIR"] = temporary_root

        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            if cancel_event is not None and cancel_event.is_set():
                return _result("cancelled", started, secrets=secrets)
            try:
                process = subprocess.Popen(
                    definition.argv,
                    cwd=working_root,
                    env=environment,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    start_new_session=os.name == "posix",
                )
            except OSError as exc:
                return _result("start_error", started, stderr=str(exc), secrets=secrets)

            status: Literal["passed", "failed", "timeout", "cancelled"]
            process_started = time.monotonic()
            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    status = "cancelled"
                    _terminate_process_group(process)
                    break
                if time.monotonic() - process_started >= definition.timeout_seconds:
                    status = "timeout"
                    _terminate_process_group(process)
                    break
                time.sleep(_POLL_SECONDS)
            else:
                status = "passed" if process.returncode == 0 else "failed"

            process.wait()
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout = _bounded_decode(stdout_file.read())
            stderr = _bounded_decode(stderr_file.read())
            return _result(
                status,
                started,
                exit_code=process.returncode,
                stdout=stdout,
                stderr=stderr,
                secrets=secrets,
            )


def _validate_source_tree(source_root: Path) -> None:
    if not source_root.is_dir():
        raise ValueError("allowed_root must be an existing directory")
    pending = [source_root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                if _ignored(entry.name):
                    continue
                mode = entry.stat(follow_symlinks=False).st_mode
                path = Path(entry.path)
                if stat.S_ISLNK(mode):
                    if Path(os.readlink(path)).is_absolute() or not path.resolve(
                        strict=False
                    ).is_relative_to(source_root):
                        raise ValueError("project contains a symlink that escapes allowed_root")
                elif stat.S_ISDIR(mode):
                    pending.append(path)
                elif not stat.S_ISREG(mode):
                    raise ValueError("project contains an unsupported special file")


def _ignore_entries(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if _ignored(name)}


def _ignored(name: str) -> bool:
    return name in _IGNORED_NAMES or name.endswith(".pyc")


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=0.2)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait()
    except ProcessLookupError:
        pass


def _bounded_decode(value: bytes) -> str:
    marker = b"\n... output truncated ...\n"
    if len(value) > _OUTPUT_LIMIT:
        room = _OUTPUT_LIMIT - len(marker)
        value = value[: room // 2] + marker + value[-(room - room // 2) :]
    return value.decode("utf-8", errors="replace")


def _result(
    status: CheckStatus,
    started: float,
    *,
    exit_code: int | None = None,
    stdout: str = "",
    stderr: str = "",
    secrets: set[str],
) -> CheckResult:
    safe_stdout = str(mask_audit_data(stdout, secrets))
    safe_stderr = str(mask_audit_data(stderr, secrets))
    return CheckResult(
        status=status,
        exit_code=exit_code,
        duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        stdout=_bounded_decode(safe_stdout.encode()),
        stderr=_bounded_decode(safe_stderr.encode()),
    )
