from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def _forgeagent_process(
    argv: list[str], stdin: bytes, env: dict[str, str]
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        argv,
        input=stdin,
        capture_output=True,
        text=False,
        env=env,
        check=False,
    )


def _command(*args: str) -> list[str]:
    executable = Path(__file__).parents[1] / ".venv" / "bin" / "forgeagent"
    return [str(executable), *args]


@pytest.fixture
def isolated_cli_env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    (home / ".forgeagent").mkdir(parents=True)
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "NO_COLOR": "1",
            "TERM": "dumb",
            "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
        }
    )
    return env


def _write_mcp_config(
    env: dict[str, str], *, mode: str, required: bool = False, pid_file: Path | None = None
) -> None:
    fixture = Path(__file__).with_name("mcp_fixture_server.py").resolve()
    child_env = {
        "FORGE_TEST_MCP_NAME": "fixture",
        "FORGE_TEST_MCP_MODE": mode,
    }
    if pid_file is not None:
        child_env["FORGE_TEST_MCP_PID_FILE"] = str(pid_file)
    config = {
        "mcpServers": {
            "fixture": {
                "command": sys.executable,
                "args": [str(fixture)],
                "env": child_env,
                "required": required,
                "autoApprove": ["echo"],
            }
        }
    }
    path = Path(env["HOME"]) / ".forgeagent" / "mcp.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")


def _scripted_model_command(tmp_path: Path) -> list[str]:
    launcher = tmp_path / "cli_model_launcher.py"
    launcher.write_text(
        "from forgeagent.cli import main\n"
        "from forgeagent.client import MockClient\n"
        "from forgeagent.models import AssistantMessage, TokenUsage\n"
        "\n"
        "def factory(_model):\n"
        "    return MockClient(script=[\n"
        "        AssistantMessage(\n"
        "            content=(\n"
        '                \'<!-- ToolCall: {"name":"MCP","arguments":\'\n'
        '                \'{"server":"fixture","tool":"echo","arguments":\'\n'
        '                \'{"text":"connected"}}} -->\'\n'
        "            ),\n"
        "            usage=TokenUsage(), stop_reason='end_turn',\n"
        "        ),\n"
        "        AssistantMessage(\n"
        "            content=(\n"
        "                '---\\ntask_status:\\n  completed: true\\n'\n"
        "                '  confidence: 0.9\\n---\\nPIPE_RESULT'\n"
        "            ),\n"
        "            usage=TokenUsage(), stop_reason='end_turn',\n"
        "        ),\n"
        "    ])\n"
        "\n"
        "raise SystemExit(main(['--model', 'mock'], client_factory=factory))\n",
        encoding="utf-8",
    )
    return [sys.executable, str(launcher)]


def test_pipe_quit_has_no_startup_bytes(isolated_cli_env: dict[str, str]):
    result = _forgeagent_process(_command(), b"quit\n", isolated_cli_env)

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stdout == b""
    assert result.stderr == b""


def test_importing_cli_does_not_load_evaluator_modules(isolated_cli_env: dict[str, str]):
    result = _forgeagent_process(
        [
            sys.executable,
            "-c",
            (
                "import sys; import forgeagent.cli; "
                "print('forgeagent.evaluator' in sys.modules, "
                "'forgeagent.evaluation' in sys.modules)"
            ),
        ],
        b"",
        isolated_cli_env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == b"False False\n"
    assert result.stderr == b""


def test_pipe_optional_mcp_chatter_has_no_startup_bytes(isolated_cli_env: dict[str, str]):
    _write_mcp_config(isolated_cli_env, mode="startup_chatter")

    result = _forgeagent_process(_command(), b"quit\n", isolated_cli_env)

    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b""


def test_pipe_optional_docker_failure_has_no_startup_bytes(isolated_cli_env: dict[str, str]):
    _write_mcp_config(isolated_cli_env, mode="docker_failure")

    result = _forgeagent_process(_command(), b"quit\n", isolated_cli_env)

    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b""


def test_pipe_goal_connects_mcp_and_only_outputs_task_result(
    isolated_cli_env: dict[str, str], tmp_path: Path
):
    pid_file = tmp_path / "mcp.pid"
    _write_mcp_config(isolated_cli_env, mode="normal", pid_file=pid_file)

    result = _forgeagent_process(
        _scripted_model_command(tmp_path), b"use available tools\n", isolated_cli_env
    )

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stderr == b""
    assert pid_file.exists()
    assert result.stdout == (
        b"completed\n"
        b"  round 1 [MCP] ok\n"
        b"PIPE_RESULT\n"
        b"execution evidence:\n"
        b"    1 MCP succeeded\n"
        b"usage: in=0 out=0 cached=0 reasoning=0 (session total) cache_hit=n/a\n"
    )
    assert b"fixture:echo" not in result.stdout


def test_required_mcp_failure_is_stderr_only(isolated_cli_env: dict[str, str]):
    _write_mcp_config(isolated_cli_env, mode="docker_failure", required=True)

    result = _forgeagent_process(_command(), b"", isolated_cli_env)

    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == b"MCP startup error: required_server_unavailable\n"
