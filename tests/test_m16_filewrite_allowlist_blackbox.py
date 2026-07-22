from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

REPO_ROOT = Path(__file__).resolve().parents[1]


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
            task_id = "0123456789abcdef0123456789abcdef"
            target_operation = "file/m16-allowlist.txt"
            target_content = "M16 FileWrite allowlist verified."
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
                    json.loads(self.rfile.read(length))
                    if mode == "filewrite":
                        allowed = target_operation in config["allowlist"]
                        decision = "preapproved" if allowed else "denied"
                        tool_status = "success" if allowed else "failed"
                        operation_id = f"operation-{decision}"
                        append_audit(
                            [
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
                        )
                        if allowed:
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
                        self.send_json(
                            200,
                            {"task_id": task_id, "status": "completed", "reason": "completed"},
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


def run_script(tmp_path: Path, mode: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "M16_FORGEAGENT_BIN": str(write_fake_forgeagent(tmp_path)),
        "M16_PYTHON_BIN": sys.executable,
        "M16_EVIDENCE_DIR": str(tmp_path / "evidence"),
        "M16_TIMEOUT_SECONDS": "5",
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


def test_blackbox_script_passes_exact_two_phase_contract(tmp_path: Path) -> None:
    result = run_script(tmp_path, "filewrite")

    assert result.returncode == 0
    assert "PASS: empty allowlist denied FileWrite" in result.stdout
    assert "PASS: exact allowlist preapproved FileWrite" in result.stdout


def test_blackbox_script_reports_model_tool_drift_as_inconclusive(tmp_path: Path) -> None:
    result = run_script(tmp_path, "no-filewrite")

    assert result.returncode == 2
    assert "INCONCLUSIVE" in result.stderr
