from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_GOAL = (
    'Use exactly one FileWrite tool call to write the exact text "M16 FileWrite '
    'allowlist verified." to relative path "m16-allowlist.txt". Do not use Exec, '
    "MCP, Python, shell, or any other tool. After the FileWrite result, report "
    "completion without another tool call."
)


def write_fake_forgeagent(tmp_path: Path) -> Path:
    fake = tmp_path / "forgeagent"
    fake.write_text(
        f"#!{sys.executable}\n"
        + dedent(
            r"""
            import json
            import os
            import signal
            import sys
            from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
            from pathlib import Path


            def load_config(path):
                values = {}
                allowlist = []
                in_allowlist = False
                for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if in_allowlist and line.startswith("- "):
                        allowlist.append(json.loads(line[2:]))
                        continue
                    key, raw_value = line.split(":", 1)
                    raw_value = raw_value.strip()
                    in_allowlist = key == "allowlist"
                    if in_allowlist:
                        if raw_value == "[]":
                            allowlist = []
                        continue
                    values[key] = json.loads(raw_value)
                values["allowlist"] = allowlist
                return values


            if len(sys.argv) != 4 or sys.argv[1:3] != ["serve", "--config"]:
                raise SystemExit(64)

            config = load_config(sys.argv[3])
            allowed_root = Path(config["allowed_root"])
            audit_path = Path(config["audit_path"])
            expected_token = os.environ["FORGEAGENT_HTTP_TOKEN"]
            evidence_dir = allowed_root.parent
            (evidence_dir / "fake-bearer-token.txt").write_text(
                expected_token,
                encoding="utf-8",
            )
            with (evidence_dir / "fake-server-pids.txt").open("a", encoding="utf-8") as handle:
                handle.write(f"{os.getpid()}\n")
            task_id = "0123456789abcdef0123456789abcdef"
            target_operation = "file/m16-allowlist.txt"
            target_content = "M16 FileWrite allowlist verified."
            expected_goal = (
                'Use exactly one FileWrite tool call to write the exact text "M16 FileWrite '
                'allowlist verified." to relative path "m16-allowlist.txt". Do not use Exec, '
                "MCP, Python, shell, or any other tool. After the FileWrite result, report "
                "completion without another tool call."
            )
            submitted_goals_path = allowed_root.parent / "submitted-goals.jsonl"
            mode = os.environ.get("FAKE_M16_MODE", "filewrite")


            def append_audit(events):
                audit_path.parent.mkdir(parents=True, exist_ok=True)
                descriptor = os.open(
                    audit_path,
                    os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                    0o600,
                )
                with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
                    for event in events:
                        handle.write(json.dumps(event, separators=(",", ":")) + "\n")


            class Handler(BaseHTTPRequestHandler):
                protocol_version = "HTTP/1.1"

                def authorized(self):
                    return self.headers.get("Authorization") == f"Bearer {expected_token}"

                def send_json(self, status, payload):
                    body = json.dumps(payload, separators=(",", ":")).encode()
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def do_POST(self):
                    if not self.authorized():
                        self.send_json(401, {"error": {"kind": "unauthorized"}})
                        return
                    if self.path != "/tasks":
                        self.send_json(404, {"error": {"kind": "not_found"}})
                        return
                    length = int(self.headers.get("Content-Length", "0"))
                    request = json.loads(self.rfile.read(length))
                    assert request == {"goal": expected_goal}
                    with submitted_goals_path.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(request["goal"]) + "\n")
                    if mode in {
                        "filewrite",
                        "filewrite-extra-tool",
                        "denied-token-leak",
                        "wrong-decision-extra-tool",
                        "allowed-wrong-decision-extra-tool",
                        "audit-degraded",
                        "queued-forever",
                        "wrong-allowlist-decision",
                    }:
                        allowed = target_operation in config["allowlist"]
                        if mode in {
                            "wrong-decision-extra-tool",
                            "wrong-allowlist-decision",
                        } and not allowed:
                            decision = "preapproved"
                        elif mode == "allowed-wrong-decision-extra-tool" and allowed:
                            decision = "denied"
                        else:
                            decision = "preapproved" if allowed else "denied"
                        tool_status = "success" if decision == "preapproved" else "failed"
                        operation_id = f"operation-{decision}"
                        events = [
                            {
                                "task_id": task_id,
                                "event_type": "confirmation.decision",
                                "operation_id": operation_id,
                                "parameters": {"operation": target_operation},
                                "result_status": decision,
                            },
                            {
                                "task_id": task_id,
                                "event_type": "tool.operation",
                                "operation_id": operation_id,
                                "parameters": {"tool": "FileWrite"},
                                "result_status": tool_status,
                            },
                        ]
                        extra_tool = mode in {
                            "filewrite-extra-tool",
                            "wrong-decision-extra-tool",
                        } or (mode == "allowed-wrong-decision-extra-tool" and allowed)
                        if extra_tool:
                            events.append(
                                {
                                    "task_id": task_id,
                                    "event_type": "tool.operation",
                                    "operation_id": "operation-extra",
                                    "parameters": {"tool": "Exec"},
                                    "result_status": "success",
                                }
                            )
                        if mode == "denied-token-leak" and not allowed:
                            events.append(
                                {
                                    "task_id": task_id,
                                    "event_type": "fake.token_leak",
                                    "operation_id": "operation-leak",
                                    "parameters": {"token": expected_token},
                                    "result_status": "recorded",
                                }
                            )
                        append_audit(events)
                        if allowed and decision == "preapproved":
                            (allowed_root / "m16-allowlist.txt").write_text(
                                target_content,
                                encoding="utf-8",
                            )
                    else:
                        append_audit(
                            [
                                {
                                    "task_id": task_id,
                                    "event_type": "llm.outcome",
                                    "operation_id": "model-only",
                                    "parameters": {},
                                    "result_status": "completed",
                                }
                            ]
                        )
                    self.send_json(202, {"task_id": task_id, "status": "queued"})

                def do_GET(self):
                    if not self.authorized():
                        self.send_json(401, {"error": {"kind": "unauthorized"}})
                        return
                    if self.path == f"/tasks/{task_id}":
                        status = "queued" if mode == "queued-forever" else "completed"
                        self.send_json(
                            200,
                            {
                                "task_id": task_id,
                                "status": status,
                                "reason": "completed",
                                "audit_degraded": mode == "audit-degraded",
                            },
                        )
                        return
                    self.send_json(404, {"error": {"kind": "not_found"}})

                def log_message(self, format, *args):
                    del format, args


            server = ThreadingHTTPServer(("127.0.0.1", config["port"]), Handler)
            signal.signal(signal.SIGTERM, lambda *_args: sys.exit(0))
            server.serve_forever()
            """
        ),
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    return fake


def run_script(
    tmp_path: Path, mode: str, *, timeout_seconds: str = "5"
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "M16_FORGEAGENT_BIN": str(write_fake_forgeagent(tmp_path)),
        "M16_PYTHON_BIN": sys.executable,
        "M16_EVIDENCE_DIR": str(tmp_path / "evidence"),
        "M16_TIMEOUT_SECONDS": timeout_seconds,
        "FAKE_M16_MODE": mode,
    }
    return subprocess.run(
        ["bash", "scripts/m16-filewrite-allowlist-blackbox.sh"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


def assert_evidence_retained(tmp_path: Path, *phases: str) -> None:
    evidence_dir = tmp_path / "evidence"
    assert evidence_dir.is_dir()
    for phase in phases:
        phase_dir = evidence_dir / phase
        assert phase_dir.is_dir()
        for filename in ("config.yaml", "audit.jsonl", "terminal.json", "server.log"):
            assert (phase_dir / filename).is_file()


def assert_fake_servers_stopped(tmp_path: Path) -> None:
    pid_path = tmp_path / "evidence/fake-server-pids.txt"
    pids = [int(line) for line in pid_path.read_text(encoding="utf-8").splitlines()]
    assert pids
    for pid in pids:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_blackbox_script_passes_exact_two_phase_contract(tmp_path: Path) -> None:
    result = run_script(tmp_path, "filewrite")

    assert result.returncode == 0
    assert "PASS: empty allowlist denied FileWrite" in result.stdout
    assert "PASS: exact allowlist preapproved FileWrite" in result.stdout
    submitted_goal_lines = (
        (tmp_path / "evidence/submitted-goals.jsonl").read_text(encoding="utf-8").splitlines()
    )
    assert submitted_goal_lines[0] == submitted_goal_lines[1]
    assert [json.loads(line) for line in submitted_goal_lines] == [EXPECTED_GOAL, EXPECTED_GOAL]
    assert "Do not use Exec, MCP, Python, shell, or any other tool." in EXPECTED_GOAL
    assert_evidence_retained(tmp_path, "denied", "allowed")
    assert_fake_servers_stopped(tmp_path)


def test_blackbox_script_reports_model_tool_drift_as_inconclusive(tmp_path: Path) -> None:
    result = run_script(tmp_path, "no-filewrite")

    assert result.returncode == 2
    assert "INCONCLUSIVE" in result.stderr
    assert_evidence_retained(tmp_path, "denied")
    assert_fake_servers_stopped(tmp_path)


def test_blackbox_script_rejects_forbidden_extra_tool_as_inconclusive(tmp_path: Path) -> None:
    result = run_script(tmp_path, "filewrite-extra-tool")

    assert result.returncode == 2
    assert "INCONCLUSIVE" in result.stderr


def test_tool_drift_takes_precedence_over_wrong_allowlist_decision(tmp_path: Path) -> None:
    result = run_script(tmp_path, "wrong-decision-extra-tool")

    assert result.returncode == 2
    assert "INCONCLUSIVE" in result.stderr


def test_allowed_phase_tool_drift_precedes_wrong_decision(tmp_path: Path) -> None:
    result = run_script(tmp_path, "allowed-wrong-decision-extra-tool")

    assert result.returncode == 2
    assert "PASS: empty allowlist denied FileWrite" in result.stdout
    assert "The model emitted additional tool operations." in result.stderr
    submitted_goals = (
        (tmp_path / "evidence/submitted-goals.jsonl").read_text(encoding="utf-8").splitlines()
    )
    assert len(submitted_goals) == 2


def test_blackbox_script_rejects_token_leak_in_denied_audit(tmp_path: Path) -> None:
    result = run_script(tmp_path, "denied-token-leak")

    assert result.returncode == 1
    assert "Bearer token appeared in the audit log." in result.stderr
    bearer_token = (tmp_path / "evidence/fake-bearer-token.txt").read_text(encoding="utf-8")
    assert bearer_token not in result.stdout
    assert bearer_token not in result.stderr
    config_paths = list((tmp_path / "evidence").glob("*/config.yaml"))
    assert config_paths
    assert all(bearer_token not in path.read_text(encoding="utf-8") for path in config_paths)
    assert_evidence_retained(tmp_path, "denied")
    assert_fake_servers_stopped(tmp_path)


def test_blackbox_script_rejects_degraded_terminal_audit(tmp_path: Path) -> None:
    result = run_script(tmp_path, "audit-degraded")

    assert result.returncode == 1
    assert "audit_degraded" in result.stderr
    assert_evidence_retained(tmp_path, "denied")
    assert_fake_servers_stopped(tmp_path)


def test_blackbox_script_times_out_and_stops_queued_server(tmp_path: Path) -> None:
    result = run_script(tmp_path, "queued-forever", timeout_seconds="1")

    assert result.returncode == 1
    assert "did not reach a terminal state within 1 seconds" in result.stderr
    assert_evidence_retained(tmp_path, "denied")
    assert_fake_servers_stopped(tmp_path)


def test_blackbox_script_reports_wrong_allowlist_decision_as_failure(tmp_path: Path) -> None:
    result = run_script(tmp_path, "wrong-allowlist-decision")

    assert result.returncode == 1
    assert "Empty allowlist preapproved the target FileWrite." in result.stderr
    assert_evidence_retained(tmp_path, "denied")
    assert_fake_servers_stopped(tmp_path)


def test_blackbox_script_reports_evidence_for_invalid_timeout(tmp_path: Path) -> None:
    result = run_script(tmp_path, "filewrite", timeout_seconds="invalid")

    assert result.returncode == 1
    assert (tmp_path / "evidence").is_dir()
    assert f"Evidence directory: {tmp_path / 'evidence'}" in result.stderr
