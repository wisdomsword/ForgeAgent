"""Security and lifecycle contracts for host-defined evaluator checks."""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

import forgeagent.check_runner as check_runner_module
from forgeagent.check_runner import CheckDefinition, run_check
from forgeagent.secret_policy import REDACTED, REDACTED_PATH


def _python_check(check_id: str, code: str, *, timeout: float = 2.0) -> CheckDefinition:
    return CheckDefinition(id=check_id, argv=(sys.executable, "-c", code), timeout_seconds=timeout)


def test_check_runs_in_temporary_copy_and_preserves_real_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    temporary_roots: list[Path] = []
    original_temporary_directory = check_runner_module.tempfile.TemporaryDirectory

    class RecordingTemporaryDirectory:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            self._inner = original_temporary_directory(*args, **kwargs)

        def __enter__(self):
            path = self._inner.__enter__()
            temporary_roots.append(Path(path))
            return path

        def __exit__(self, *args):  # noqa: ANN002
            return self._inner.__exit__(*args)

    monkeypatch.setattr(
        check_runner_module.tempfile, "TemporaryDirectory", RecordingTemporaryDirectory
    )
    (tmp_path / "data.txt").write_text("original", encoding="utf-8")
    check = _python_check(
        "mutate-copy",
        "from pathlib import Path; "
        "Path('data.txt').write_text('changed'); "
        "Path('new.txt').write_text('new'); "
        "print(Path.cwd())",
    )

    result = run_check(check, allowed_root=tmp_path)

    assert result.status == "passed"
    assert result.exit_code == 0
    assert (tmp_path / "data.txt").read_text(encoding="utf-8") == "original"
    assert not (tmp_path / "new.txt").exists()
    assert str(tmp_path) not in result.stdout
    assert REDACTED_PATH in result.stdout
    assert temporary_roots and all(not path.exists() for path in temporary_roots)


def test_check_receives_only_minimal_environment_and_definition_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("FORGE_CHECK_SECRET", "top-secret-check-value")
    check = CheckDefinition(
        id="environment",
        argv=(
            sys.executable,
            "-c",
            "import os; print(os.getenv('FORGE_CHECK_SECRET')); print(os.getenv('CHECK_VALUE'))",
        ),
        env={"CHECK_VALUE": "available"},
    )

    result = run_check(check, allowed_root=tmp_path)

    assert result.status == "passed"
    assert result.stdout.splitlines() == ["None", "available"]
    with pytest.raises(ValidationError):
        CheckDefinition(id="bad-env", argv=(sys.executable, "-V"), env={"API_KEY": "secret"})


@pytest.mark.parametrize("mode", ["timeout", "cancel"])
def test_check_terminates_process_group_on_timeout_or_cancel(tmp_path: Path, mode: str):
    code = (
        "import subprocess, sys, time; "
        "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        "print(child.pid, flush=True); time.sleep(30)"
    )
    cancel_event = threading.Event()
    timeout = 0.08 if mode == "timeout" else 5.0
    if mode == "cancel":
        threading.Timer(0.08, cancel_event.set).start()

    started = time.monotonic()
    result = run_check(
        _python_check(mode, code, timeout=timeout),
        allowed_root=tmp_path,
        cancel_event=cancel_event,
    )

    assert result.status == mode + ("led" if mode == "cancel" else "")
    assert time.monotonic() - started < 2
    child_pid = int(result.stdout.strip())
    for _ in range(40):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.025)
    else:
        pytest.fail("child process survived process-group termination")


def test_check_bounds_and_masks_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    secret = "check-output-secret-value"
    monkeypatch.setenv("FORGE_CHECK_TOKEN", secret)
    code = f"import sys; print({secret!r}); print('x' * 40000); sys.exit(7)"

    result = run_check(_python_check("bounded-output", code), allowed_root=tmp_path)

    assert result.status == "failed"
    assert result.exit_code == 7
    assert secret not in result.stdout
    assert REDACTED in result.stdout
    assert "output truncated" in result.stdout
    assert len(result.stdout.encode()) <= 17 * 1024


def test_check_rejects_copy_escape_before_process_start(tmp_path: Path):
    outside = tmp_path.parent / "outside-check-target"
    outside.write_text("outside", encoding="utf-8")
    (tmp_path / "escape").symlink_to(outside)

    result = run_check(_python_check("copy-escape", "print('must not run')"), allowed_root=tmp_path)

    assert result.status == "copy_error"
    assert result.exit_code is None
    assert "must not run" not in result.stdout


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO is unavailable")
def test_check_rejects_special_file_before_process_start(tmp_path: Path):
    os.mkfifo(tmp_path / "pipe")

    result = run_check(
        _python_check("special-file", "print('must not run')"), allowed_root=tmp_path
    )

    assert result.status == "copy_error"
    assert "must not run" not in result.stdout


def test_pre_cancelled_check_does_not_start_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cancel_event = threading.Event()
    cancel_event.set()
    monkeypatch.setattr(
        check_runner_module.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("pre-cancelled check started a process"),
    )

    result = run_check(
        _python_check("pre-cancelled", "print('must not run')"),
        allowed_root=tmp_path,
        cancel_event=cancel_event,
    )

    assert result.status == "cancelled"
