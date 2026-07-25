"""Run host-defined Python evaluator checks against a disposable project copy."""

from __future__ import annotations

import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import BinaryIO, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .secret_policy import is_secret_name, mask_audit_data, sensitive_env_values

_OUTPUT_LIMIT = 16 * 1024
_TRUNCATION_MARKER = b"\n... output truncated ...\n"
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
_ENV_ALLOWLIST = {"LANG", "LC_ALL", "PATH", "SYSTEMROOT"}
CheckStatus = Literal["passed", "failed", "timeout", "cancelled", "copy_error", "start_error"]


class CheckDefinition(BaseModel):
    """A trusted, server-owned Python invocation exposed by identifier."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    argv: tuple[str, ...] = Field(min_length=2)
    timeout_seconds: float = Field(default=60.0, ge=0.01, le=3600.0)
    env: dict[str, str] = Field(default_factory=dict)

    @field_validator("argv")
    @classmethod
    def _validate_argv(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item or "\x00" in item for item in value):
            raise ValueError("argv entries must be non-empty and contain no NUL bytes")
        if Path(value[0]).resolve() != Path(sys.executable).resolve():
            raise ValueError("check command must use the current Python interpreter")
        invocation = value[1:]
        if invocation[0] in {"-c", "-m"}:
            if len(invocation) < 2:
                raise ValueError("Python check invocation is incomplete")
        elif not invocation[0].startswith("-"):
            script = Path(invocation[0])
            if script.is_absolute() or ".." in script.parts or script.suffix != ".py":
                raise ValueError("check script must be a relative Python file")
        else:
            raise ValueError("unsupported Python check invocation")
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
    except (OSError, RuntimeError, ValueError) as exc:
        return _result("copy_error", started, stderr=str(exc), secrets=secrets)

    with tempfile.TemporaryDirectory(prefix="forgeagent-check-") as temporary_root:
        working_root = Path(temporary_root) / "project"
        try:
            shutil.copytree(source_root, working_root, ignore=_ignore_entries)
        except (OSError, shutil.Error) as exc:
            return _result("copy_error", started, stderr=str(exc), secrets=secrets)

        check_tmp = working_root / ".check-tmp"
        check_tmp.mkdir()
        environment = {name: value for name, value in os.environ.items() if name in _ENV_ALLOWLIST}
        environment.update(definition.env)
        environment.update(
            {
                "FORGEAGENT_CHECK_ROOT": str(working_root),
                "TMPDIR": str(check_tmp),
                "TEMP": str(check_tmp),
                "TMP": str(check_tmp),
            }
        )
        if cancel_event is not None and cancel_event.is_set():
            return _result("cancelled", started, secrets=secrets)
        try:
            process = subprocess.Popen(
                [sys.executable, "-I", "-m", "forgeagent._check_worker", *definition.argv[1:]],
                cwd=working_root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=os.name == "posix",
            )
        except OSError as exc:
            return _result("start_error", started, stderr=str(exc), secrets=secrets)

        assert process.stdout is not None and process.stderr is not None
        stdout_capture = _BoundedCapture(process.stdout)
        stderr_capture = _BoundedCapture(process.stderr)
        stdout_capture.start()
        stderr_capture.start()
        process_started = time.monotonic()
        status: Literal["passed", "failed", "timeout", "cancelled"]
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
        stdout_capture.join()
        stderr_capture.join()
        return _result(
            status,
            started,
            exit_code=process.returncode,
            stdout=stdout_capture.text(),
            stderr=stderr_capture.text(),
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
                if stat.S_ISLNK(mode):
                    raise ValueError("project contains an unsupported symlink")
                if stat.S_ISDIR(mode):
                    pending.append(Path(entry.path))
                elif not stat.S_ISREG(mode):
                    raise ValueError("project contains an unsupported special file")


def _ignore_entries(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if _ignored(name)}


def _ignored(name: str) -> bool:
    return name in _IGNORED_NAMES or name.endswith(".pyc")


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            process.kill()
    process.wait()


class _BoundedCapture:
    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._data = bytearray()
        self._head = bytearray()
        self._tail = bytearray()
        self._truncated = False
        self._thread = threading.Thread(target=self._read, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def join(self) -> None:
        self._thread.join()

    def text(self) -> str:
        if not self._truncated:
            return bytes(self._data).decode("utf-8", errors="replace")
        return (bytes(self._head) + _TRUNCATION_MARKER + bytes(self._tail)).decode(
            "utf-8", errors="replace"
        )

    def _read(self) -> None:
        half = (_OUTPUT_LIMIT - len(_TRUNCATION_MARKER)) // 2
        while chunk := self._stream.read(8192):
            if not self._truncated and len(self._data) + len(chunk) <= _OUTPUT_LIMIT:
                self._data.extend(chunk)
                continue
            if not self._truncated:
                combined = self._data + chunk
                self._head.extend(combined[:half])
                self._tail.extend(combined[-half:])
                self._data.clear()
                self._truncated = True
                continue
            self._tail.extend(chunk)
            if len(self._tail) > half:
                del self._tail[:-half]


def _bounded_decode(value: bytes) -> str:
    if len(value) > _OUTPUT_LIMIT:
        room = _OUTPUT_LIMIT - len(_TRUNCATION_MARKER)
        value = value[: room // 2] + _TRUNCATION_MARKER + value[-(room - room // 2) :]
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
