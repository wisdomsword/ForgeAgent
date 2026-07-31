from __future__ import annotations

import ast
import hashlib
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest


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


@pytest.mark.parametrize(("argv", "stdout_bytes", "stdout_sha256"), HELP_BASELINE)
def test_cli_help_output_matches_m41_baseline(
    argv: tuple[str, ...], stdout_bytes: int, stdout_sha256: str
) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "forgeagent.cli", *argv],
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0
    assert len(result.stdout) == stdout_bytes
    assert hashlib.sha256(result.stdout).hexdigest() == stdout_sha256
    assert hashlib.sha256(result.stderr).hexdigest() == EMPTY_SHA256
