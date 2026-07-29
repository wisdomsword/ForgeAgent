#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.resources
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from collections.abc import Mapping
from email.parser import Parser
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import forgeagent
from forgeagent import HttpServiceConfig, TaskService, create_http_server
from forgeagent.client import MockClient
from forgeagent.collaboration import CollaborationRunner
from forgeagent.models import AssistantMessage, TokenUsage
from forgeagent.secret_policy import is_secret_name
from forgeagent.step import Termination
from forgeagent.task import Task, TaskOutcome, TaskStatus

SCHEMA = "forgeagent.release-candidate-smoke/v1"
VERSION = "0.1.0"
CHECK_NAMES = ("clean-wheel", "cli", "http", "single", "duo", "triad")


def clean_environment(source: Mapping[str, str], home: Path) -> dict[str, str]:
    cleaned = {
        name: value
        for name, value in source.items()
        if name not in {"PYTHONHOME", "PYTHONPATH"} and not is_secret_name(name)
    }
    cleaned["HOME"] = str(home)
    return cleaned


def wheel_identity(path: Path) -> tuple[str, str]:
    try:
        mode = path.lstat().st_mode
    except OSError as error:
        raise ValueError("wheel must be a regular file") from error
    if not stat.S_ISREG(mode):
        raise ValueError("wheel must be a regular file")

    try:
        with zipfile.ZipFile(path) as archive:
            metadata_names = [
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_names) != 1:
                raise ValueError("wheel metadata is invalid")
            metadata = Parser().parsestr(archive.read(metadata_names[0]).decode("utf-8"))
    except (OSError, UnicodeError, zipfile.BadZipFile) as error:
        raise ValueError("wheel metadata is invalid") from error

    if metadata.get("Name") != "forgeagent" or metadata.get("Version") != VERSION:
        raise ValueError("wheel metadata is invalid")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return VERSION, digest


def new_report(wheel_sha256: str) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "python": ".".join(map(str, sys.version_info[:3])),
        "wheel_sha256": wheel_sha256,
        "passed": False,
        "checks": dict.fromkeys(CHECK_NAMES, "not-run"),
    }


def finalize_report(report: dict[str, object]) -> None:
    checks = report["checks"]
    report["passed"] = isinstance(checks, dict) and all(
        checks.get(name) == "passed" for name in CHECK_NAMES
    )


def write_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(report, temporary, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def check_cli(console: Path, environment: Mapping[str, str]) -> None:
    help_result = subprocess.run(
        [str(console), "--help"],
        capture_output=True,
        text=True,
        env=environment,
        shell=False,
        timeout=30,
    )
    models_result = subprocess.run(
        [str(console), "models"],
        capture_output=True,
        text=True,
        env=environment,
        shell=False,
        timeout=30,
    )
    if help_result.returncode != 0 or models_result.returncode != 0:
        raise RuntimeError("CLI check failed")
    if (
        not all(
            marker in help_result.stdout
            for marker in ("Lightweight code-as-action agent", "run", "serve")
        )
        or "claude-sonnet-5" not in models_result.stdout
    ):
        raise RuntimeError("CLI check failed")


def _http_request(
    address: tuple[str, int], method: str, path: str, *, token: str | None, body: object
) -> tuple[int, dict[str, object]]:
    payload = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        f"http://{address[0]}:{address[1]}{path}",
        data=payload,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def check_http() -> None:
    baseline_threads = set(threading.enumerate())

    class ControlledTask:
        def run(self, goal: str, *, cancel_event: threading.Event | None = None) -> TaskOutcome:
            if not goal or cancel_event is None:
                raise RuntimeError("controlled task requires cancellation")
            deadline = time.monotonic() + 5
            while not cancel_event.wait(0.01):
                if time.monotonic() >= deadline:
                    raise TimeoutError("controlled task was not cancelled")
            return TaskOutcome(
                status=TaskStatus(completed=False, reason=Termination.CANCELLED), rounds=[]
            )

        def close(self) -> None:
            return None

    token = "m28-local-token"
    config = HttpServiceConfig(
        bind_host="127.0.0.1", port=0, token=token, max_workers=1, max_queue=1, max_records=2
    )
    service = TaskService(factory=lambda _record: ControlledTask(), config=config)
    server = create_http_server(config, service)
    thread = threading.Thread(target=server.serve_forever, name="m28-http-smoke", daemon=True)
    thread.start()
    try:
        status, _ = _http_request(
            server.server_address, "POST", "/tasks", token=None, body={"goal": "smoke"}
        )
        if status != 401 or service.records:
            raise RuntimeError("HTTP authorization check failed")
        status, submitted = _http_request(
            server.server_address, "POST", "/tasks", token=token, body={"goal": "smoke"}
        )
        task_id = submitted.get("task_id")
        if status != 202 or not isinstance(task_id, str) or len(task_id) != 32:
            raise RuntimeError("HTTP submit check failed")
        status, queried = _http_request(
            server.server_address, "GET", f"/tasks/{task_id}", token=token, body=None
        )
        if status != 200 or queried.get("status") not in {"queued", "running"}:
            raise RuntimeError("HTTP query check failed")
        status, _ = _http_request(
            server.server_address,
            "POST",
            f"/tasks/{task_id}/cancel",
            token=token,
            body={},
        )
        if status not in {200, 202}:
            raise RuntimeError("HTTP cancel check failed")
        final = service.wait(task_id, timeout=3)
        if final.get("status") != "cancelled":
            raise RuntimeError("HTTP cancellation did not complete")
        status, queried = _http_request(
            server.server_address, "GET", f"/tasks/{task_id}", token=token, body=None
        )
        if status != 200 or queried.get("status") != "cancelled":
            raise RuntimeError("HTTP terminal query failed")
    finally:
        server.shutdown()
        server.server_close()
        service.shutdown(3)
        thread.join(timeout=3)
    deadline = time.monotonic() + 3
    owned_threads = [thread]
    while time.monotonic() < deadline:
        owned_threads = [
            candidate
            for candidate in threading.enumerate()
            if candidate not in baseline_threads
            and candidate.name.startswith(("m28-http-smoke", "forgeagent-task"))
        ]
        if not owned_threads:
            break
        time.sleep(0.01)
    if owned_threads:
        raise RuntimeError("HTTP server did not close")


def _reply(content: str) -> AssistantMessage:
    return AssistantMessage(content=content, usage=TokenUsage(), stop_reason="end_turn")


def check_collaboration(mode: str, root: Path) -> dict[str, str]:
    goal = "Complete the offline release candidate smoke"
    completed_reply = _reply(
        "---\ntask_status:\n  completed: true\n  confidence: 1.0\n---\ncompleted"
    )
    if mode == "single":
        task = Task(MockClient([completed_reply]), allowed_root=str(root))
        try:
            outcome = task.run(goal)
        finally:
            task.close()
        if not outcome.status.completed:
            raise RuntimeError("single collaboration check failed")
        return {"mode": mode, "status": "completed"}
    if mode not in {"duo", "triad"}:
        raise ValueError("collaboration mode is invalid")

    plan_id = "smoke" if mode == "triad" else "goal"
    scripts = {
        "planner": _reply(
            '<!-- ToolCall: {"name":"SubmitPlan","arguments":{"items":['
            '{"id":"smoke","behavior":"The smoke completes",'
            '"acceptance":"The completed status is observable"}]}} -->'
        ),
        "generator": _reply('<!-- ToolCall: {"name":"SubmitCandidate","arguments":{}} -->'),
        "evaluator": _reply(
            '<!-- ToolCall: {"name":"SubmitEvaluation","arguments":{"results":['
            f'{{"id":"{plan_id}","passed":true,"observed":"observed",'
            '"expected":"completed","location":"runtime"}]}} -->'
        ),
    }

    def role_task_builder(role, _attempt, registry, prompt):
        return Task(
            MockClient([scripts[role]]),
            allowed_root=str(root),
            tool_registry=registry,
            system_prompt=prompt,
        )

    runner = CollaborationRunner.create(
        mode=mode,
        goal=goal,
        allowed_root=str(root),
        role_task_builder=role_task_builder,
        plan_confirmer=(lambda _summary: True) if mode == "triad" else None,
        execution_tier="restricted",
    )
    try:
        report = runner.run(goal)
    finally:
        runner.close()
    if (
        report.mode != mode
        or report.status != "completed"
        or report.generator_attempts != 1
        or report.evaluator_attempts != 1
        or report.passed_item_count != 1
        or (mode == "triad" and report.plan_item_count != 1)
    ):
        raise RuntimeError("collaboration check failed")
    return {"mode": mode, "status": "completed"}


def _installed_console() -> Path:
    return Path(sys.prefix) / ("Scripts/forgeagent.exe" if os.name == "nt" else "bin/forgeagent")


def run_installed(output: Path, wheel_sha256: str) -> int:
    report = new_report(wheel_sha256)
    checks = report["checks"]
    assert isinstance(checks, dict)
    current = "clean-wheel"
    try:
        package_path = Path(forgeagent.__file__).resolve()
        prefix = Path(sys.prefix).resolve()
        console = _installed_console().resolve()
        models = importlib.resources.files("forgeagent.res").joinpath("models.yaml").read_text()
        prompt = (
            importlib.resources.files("forgeagent.res").joinpath("prompts/system.j2").read_text()
        )
        if (
            importlib.metadata.version("forgeagent") != VERSION
            or not package_path.is_relative_to(prefix)
            or not console.is_file()
            or not console.is_relative_to(prefix)
            or "claude-sonnet-5" not in models
            or "ForgeAgent Agent" not in prompt
        ):
            raise RuntimeError("installed wheel provenance check failed")
        checks[current] = "passed"

        current = "cli"
        check_cli(console, clean_environment(os.environ, Path.home()))
        checks[current] = "passed"

        current = "http"
        check_http()
        checks[current] = "passed"

        with tempfile.TemporaryDirectory(prefix="forgeagent-m28-collaboration-") as temporary:
            root = Path(temporary)
            for current in ("single", "duo", "triad"):
                check_collaboration(current, root)
                checks[current] = "passed"
    except Exception:
        checks[current] = "failed"
        finalize_report(report)
        write_report(output, report)
        print(f"M28 RC smoke failed: {current}", file=sys.stderr)
        return 1
    finalize_report(report)
    write_report(output, report)
    return 0


def run_parent(wheel: Path, output: Path, python: str) -> int:
    digest = "0" * 64
    try:
        with tempfile.TemporaryDirectory(prefix="forgeagent-m28-rc-") as temporary:
            temporary_root = Path(temporary)
            venv = temporary_root / "venv"
            probe = temporary_root / "probe"
            home = temporary_root / "home"
            snapshot = temporary_root / "forgeagent-0.1.0-py3-none-any.whl"
            source_stat = wheel.lstat()
            if not stat.S_ISREG(source_stat.st_mode):
                raise ValueError("wheel must be a regular file")
            open_flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            with (
                os.fdopen(os.open(wheel, open_flags), "rb") as source,
                snapshot.open("xb") as target,
            ):
                opened_stat = os.fstat(source.fileno())
                if (source_stat.st_dev, source_stat.st_ino) != (
                    opened_stat.st_dev,
                    opened_stat.st_ino,
                ):
                    raise ValueError("wheel changed before snapshot")
                shutil.copyfileobj(source, target)
            _, digest = wheel_identity(snapshot)
            probe.mkdir()
            home.mkdir()
            environment = clean_environment(os.environ, home)
            subprocess.run(
                [python, "-m", "venv", str(venv)],
                env=environment,
                shell=False,
                timeout=180,
                check=True,
                capture_output=True,
            )
            venv_python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            subprocess.run(
                [str(venv_python), "-m", "pip", "install", str(snapshot)],
                env=environment,
                shell=False,
                timeout=180,
                check=True,
                capture_output=True,
            )
            result = subprocess.run(
                [
                    str(venv_python),
                    "-I",
                    str(Path(__file__).resolve()),
                    "--installed",
                    "--output",
                    str(output.resolve()),
                    "--wheel-sha256",
                    digest,
                ],
                cwd=probe,
                env=environment,
                shell=False,
                timeout=180,
                check=False,
                capture_output=True,
            )
        loaded = json.loads(output.read_text())
        if result.returncode != 0:
            report = new_report(digest)
            report["checks"]["clean-wheel"] = "failed"
            write_report(output, report)
            print("M28 RC smoke failed: clean-wheel", file=sys.stderr)
            return 1
        python_match = re.fullmatch(
            r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)",
            loaded.get("python", "") if isinstance(loaded, dict) else "",
        )
        if (
            set(loaded) != {"schema", "version", "python", "wheel_sha256", "passed", "checks"}
            or loaded.get("schema") != SCHEMA
            or loaded.get("version") != VERSION
            or python_match is None
            or tuple(map(int, python_match.groups())) < (3, 11, 0)
            or loaded.get("wheel_sha256") != digest
            or loaded.get("passed") is not True
            or loaded.get("checks") != dict.fromkeys(CHECK_NAMES, "passed")
        ):
            report = new_report(digest)
            report["checks"]["clean-wheel"] = "failed"
            write_report(output, report)
            print("M28 RC smoke failed: clean-wheel", file=sys.stderr)
            return 1
        return 0
    except Exception:
        report = new_report(digest)
        report["checks"]["clean-wheel"] = "failed"
        write_report(output, report)
        print("M28 RC smoke failed: clean-wheel", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the ForgeAgent release candidate wheel.")
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--installed", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--wheel-sha256", help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    if arguments.installed:
        if arguments.wheel_sha256 is None:
            parser.error("--wheel-sha256 is required with --installed")
        return run_installed(arguments.output, arguments.wheel_sha256)
    if arguments.wheel is None:
        parser.error("--wheel is required")
    return run_parent(arguments.wheel, arguments.output, arguments.python)


if __name__ == "__main__":
    raise SystemExit(main())
