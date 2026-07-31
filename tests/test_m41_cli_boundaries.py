from __future__ import annotations

import ast
import hashlib
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src" / "forgeagent"
BOUNDARY_MODULES = (
    "_cli_parser.py",
    "_cli_collaboration.py",
    "_cli_repl.py",
    "_cli_http.py",
)
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
HELP_BASELINE = (
    (("--help",), 1608, "7b99003897c90cf32c86bfb198f251222327e03bf8e2faaeada98c89ec9c76b3"),
    (
        ("run", "--help"),
        773,
        "14a60081cb8f530692a01f3e840fd554cd4f1e9cd46a98e5483db10908e7589a",
    ),
    (
        ("loop", "--help"),
        906,
        "dc990fa9c6acc1b3a40a7cd8ba58b72384e2688d451c386bcdd0bfc541d49e8f",
    ),
    (
        ("serve", "--help"),
        159,
        "01f9c0fa42fe5fa7541f9ff53867a808aa1da1c259ecc5b79ea6b71ae309dcfc",
    ),
    (
        ("evaluate", "--help"),
        553,
        "cb8204fa8b055822b5438b8dab2aeb49d5a72d8488360e0915e32e2a181f08e7",
    ),
    (
        ("models", "--help"),
        86,
        "eab585f6c180a6c82ed779d1d977903fe935569cb181364ee3569f1d5d5aea05",
    ),
    (
        ("smoke", "--help"),
        415,
        "ef2c9b04e1e36969b6333264080ffb67aab79ebdfd9dc6a5b7de7ff68aa6dc05",
    ),
)


def _imports_cli(module_path: Path) -> bool:
    tree = ast.parse(module_path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {"cli", "forgeagent.cli"}:
            return True
        if isinstance(node, ast.Import) and any(
            alias.name == "forgeagent.cli" for alias in node.names
        ):
            return True
    return False


def test_cli_is_split_into_four_bounded_one_way_modules() -> None:
    cli_lines = len((SOURCE_ROOT / "cli.py").read_text().splitlines())
    missing = [name for name in BOUNDARY_MODULES if not (SOURCE_ROOT / name).is_file()]

    assert not missing, f"missing CLI boundary modules: {missing}"
    assert cli_lines <= 1800
    for name in BOUNDARY_MODULES:
        module_path = SOURCE_ROOT / name
        assert len(module_path.read_text().splitlines()) <= 900, name
        assert not _imports_cli(module_path), name


def test_cli_extraction_does_not_add_runtime_dependencies() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert len(project["project"]["dependencies"]) == 8


def test_cli_reexports_parser_boundary() -> None:
    import forgeagent.cli as cli
    from forgeagent import _cli_parser

    assert cli.build_parser is _cli_parser.build_parser
    assert cli._load_strict_json is _cli_parser.load_strict_json
    assert callable(_cli_parser.load_cli_context_config)
    assert callable(_cli_parser.load_required_candidate_files)


def test_real_client_facade_resolves_the_current_registry_loader(monkeypatch) -> None:
    import forgeagent.cli as cli
    from forgeagent import _cli_http

    registry = object()
    client = object()
    captured: dict[str, object] = {}

    def fake_build(model, env=None, *, registry=None):
        captured.update(model=model, env=env, registry=registry)
        return client

    monkeypatch.setattr(cli, "load_registry", lambda: registry)
    monkeypatch.setattr(_cli_http, "build_real_client", fake_build)

    assert cli.build_real_client("model", env={"API_KEY": "secret"}) is client
    assert captured == {
        "model": "model",
        "env": {"API_KEY": "secret"},
        "registry": registry,
    }


def test_startup_display_resolves_current_facade_capability_checks(monkeypatch) -> None:
    import forgeagent.cli as cli
    from forgeagent import _cli_repl

    console = Console(record=True, force_terminal=True, color_system="standard")
    monkeypatch.setattr(_cli_repl, "startup_ui_available", lambda _console: True)
    monkeypatch.setattr(cli, "_startup_ui_available", lambda _console: False)
    monkeypatch.setattr(cli, "_startup_mark_available", lambda _console: False)
    monkeypatch.setattr(
        cli,
        "Live",
        lambda **_kwargs: pytest.fail("facade capability check was bypassed"),
    )

    cli._StartupDisplay(console).start("Loading identity")


def test_cli_collaboration_boundary_exposes_explicit_bindings() -> None:
    from forgeagent import _cli_collaboration

    assert tuple(_cli_collaboration.CollaborationBindings.__dataclass_fields__) == (
        "runner_type",
        "task_type",
        "validate_context_policy",
    )


def test_cli_repl_boundary_exposes_frozen_explicit_bindings() -> None:
    from forgeagent import _cli_repl

    fields = set(_cli_repl.ReplBindings.__dataclass_fields__)
    assert _cli_repl.ReplBindings.__dataclass_params__.frozen is True
    assert {
        "build_real_client",
        "build_mcp_manager",
        "run_once",
        "run_collaboration_once",
        "load_context_config",
        "load_skill_registry",
    } <= fields


def test_cli_http_boundary_exposes_frozen_explicit_bindings() -> None:
    from forgeagent import _cli_http

    fields = set(_cli_http.HttpBindings.__dataclass_fields__)
    assert _cli_http.HttpBindings.__dataclass_params__.frozen is True
    assert {
        "task_service_type",
        "task_type",
        "loop_runner_type",
        "collaboration_runner_type",
        "build_mcp_manager",
        "load_registry",
    } <= fields


@pytest.mark.parametrize(("argv", "stdout_bytes", "stdout_sha256"), HELP_BASELINE)
def test_cli_help_output_matches_m41_baseline(
    argv: tuple[str, ...], stdout_bytes: int, stdout_sha256: str
) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "forgeagent.cli", *argv],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )

    assert result.returncode == 0
    assert len(result.stdout) == stdout_bytes
    assert hashlib.sha256(result.stdout).hexdigest() == stdout_sha256
    assert hashlib.sha256(result.stderr).hexdigest() == EMPTY_SHA256
