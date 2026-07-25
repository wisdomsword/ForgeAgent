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


def test_check_blocks_project_code_from_host_files(tmp_path: Path):
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("host secret", encoding="utf-8")
    code = f"from pathlib import Path; print(Path({str(outside)!r}).read_text())"

    result = run_check(_python_check("restricted", code), allowed_root=tmp_path)

    assert result.status == "failed"
    assert "host secret" not in result.stdout
    assert "restricted: file access outside allowed root denied" in result.stderr


@pytest.mark.parametrize("operation", ["listdir", "scandir"])
def test_check_blocks_project_code_from_listing_host_directories(tmp_path: Path, operation: str):
    outside = tmp_path.parent / f"outside-{operation}"
    outside.mkdir()
    (outside / "host-secret-name").write_text("secret", encoding="utf-8")
    code = f"import os; print(list(os.{operation}({str(outside)!r})))"

    result = run_check(_python_check(operation, code), allowed_root=tmp_path)

    assert result.status == "failed"
    assert "host-secret-name" not in result.stdout
    assert "restricted: file access outside allowed root denied" in result.stderr


@pytest.mark.parametrize(
    ("check_id", "code"),
    [
        ("remove", "import os; os.remove({outside!r})"),
        ("rename", "import os; os.rename({outside!r}, {renamed!r})"),
    ],
)
def test_check_blocks_project_code_from_mutating_host_files(
    tmp_path: Path, check_id: str, code: str
):
    outside = tmp_path.parent / f"outside-{check_id}.txt"
    renamed = tmp_path.parent / f"renamed-{check_id}.txt"
    outside.write_text("host data", encoding="utf-8")

    result = run_check(
        _python_check(check_id, code.format(outside=str(outside), renamed=str(renamed))),
        allowed_root=tmp_path,
    )

    assert result.status == "failed"
    assert "restricted: file mutation outside allowed root denied" in result.stderr
    assert outside.read_text(encoding="utf-8") == "host data"
    assert not renamed.exists()


@pytest.mark.parametrize(
    ("check_id", "code", "denial"),
    [
        (
            "network",
            "import socket; socket.create_connection(('127.0.0.1', 9))",
            "restricted: network access denied",
        ),
        (
            "sendmsg",
            "import socket; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); "
            "s.sendmsg([b'x'], [], 0, ('127.0.0.1', 9))",
            "restricted: network access denied",
        ),
        (
            "dns",
            "import socket; socket.gethostbyname('localhost')",
            "restricted: network access denied",
        ),
        (
            "process",
            "import subprocess, sys; subprocess.run([sys.executable, '-V'])",
            "restricted: process spawn denied",
        ),
        (
            "signal",
            "import os; os.kill(os.getpid(), 0)",
            "restricted: process control denied",
        ),
    ],
)
def test_check_blocks_project_code_network_and_processes(
    tmp_path: Path, check_id: str, code: str, denial: str
):
    result = run_check(_python_check(check_id, code), allowed_root=tmp_path)

    assert result.status == "failed"
    assert denial in result.stderr


@pytest.mark.parametrize("mode", ["timeout", "cancel"])
def test_check_terminates_on_timeout_or_cancel(tmp_path: Path, mode: str):
    code = "import time; print('started', flush=True); time.sleep(30)"
    cancel_event = threading.Event()
    timeout = 0.2 if mode == "timeout" else 5.0
    if mode == "cancel":
        threading.Timer(0.2, cancel_event.set).start()

    started = time.monotonic()
    result = run_check(
        _python_check(mode, code, timeout=timeout),
        allowed_root=tmp_path,
        cancel_event=cancel_event,
    )

    assert result.status == mode + ("led" if mode == "cancel" else "")
    assert time.monotonic() - started < 2
    assert result.stdout.strip() == "started"


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


def test_check_discards_unbounded_output_while_process_is_running(tmp_path: Path):
    code = "import os; chunk=b'x'*65536; [os.write(1, chunk) for _ in range(256)]"

    result = run_check(_python_check("large-output", code), allowed_root=tmp_path)

    assert result.status == "passed"
    assert "output truncated" in result.stdout
    assert len(result.stdout.encode()) <= 17 * 1024


def test_check_preserves_output_below_limit(tmp_path: Path):
    expected = "a" * (12 * 1024)

    result = run_check(
        _python_check("below-limit", f"print({expected!r}, end='')"), allowed_root=tmp_path
    )

    assert result.status == "passed"
    assert result.stdout == expected


def test_check_rejects_copy_escape_before_process_start(tmp_path: Path):
    outside = tmp_path.parent / "outside-check-target"
    outside.write_text("outside", encoding="utf-8")
    (tmp_path / "escape").symlink_to(outside)

    result = run_check(_python_check("copy-escape", "print('must not run')"), allowed_root=tmp_path)

    assert result.status == "copy_error"
    assert result.exit_code is None
    assert "must not run" not in result.stdout


def test_check_rejects_absolute_symlink_even_when_target_is_inside_project(tmp_path: Path):
    target = tmp_path / "target.txt"
    target.write_text("real project", encoding="utf-8")
    (tmp_path / "absolute-link").symlink_to(target)

    result = run_check(
        _python_check("absolute-link", "print('must not run')"), allowed_root=tmp_path
    )

    assert result.status == "copy_error"
    assert "must not run" not in result.stdout


def test_check_rejects_symlink_loop_as_copy_error(tmp_path: Path):
    (tmp_path / "a").symlink_to("b")
    (tmp_path / "b").symlink_to("a")

    result = run_check(
        _python_check("symlink-loop", "print('must not run')"), allowed_root=tmp_path
    )

    assert result.status == "copy_error"


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
