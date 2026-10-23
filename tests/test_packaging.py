"""Packaging contracts for release contents and runtime prompt resources."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path


def test_http_service_entrypoints_are_public():
    import forgeagent

    assert forgeagent.HttpServiceConfig.__name__ == "HttpServiceConfig"
    assert forgeagent.TaskService.__name__ == "TaskService"
    assert forgeagent.create_http_server.__name__ == "create_http_server"


def _clean_python_environment(environment: dict[str, str]) -> dict[str, str]:
    cleaned = environment.copy()
    cleaned.pop("PYTHONHOME", None)
    cleaned.pop("PYTHONPATH", None)
    return cleaned


def test_clean_python_environment_removes_import_overrides():
    cleaned = _clean_python_environment(
        {
            "PATH": "/usr/bin",
            "PYTHONPATH": "/untrusted/source",
            "PYTHONHOME": "/untrusted/runtime",
        }
    )

    assert cleaned == {"PATH": "/usr/bin"}


def test_wheel_and_sdist_release_contents(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    dist_dir = tmp_path / "dist"
    uv_env = os.environ.copy()
    uv_env.setdefault("UV_CACHE_DIR", str(tmp_path / "uv-cache"))
    pip_cache = repo_root / "artifacts" / "m28" / "pip-cache"
    pip_cache.mkdir(parents=True, mode=0o700, exist_ok=True)
    pip_cache.chmod(0o700)
    uv_env["PIP_CACHE_DIR"] = str(pip_cache)
    subprocess.run(
        ["uv", "build", "--out-dir", str(dist_dir)],
        cwd=repo_root,
        check=True,
        capture_output=True,
        env=uv_env,
    )
    wheels = list(dist_dir.glob("*.whl"))
    sdists = list(dist_dir.glob("*.tar.gz"))
    assert len(wheels) == 1
    assert len(sdists) == 1

    with tarfile.open(sdists[0]) as tar:
        names = tar.getnames()
    archive_roots = {name.split("/", 1)[0] for name in names}
    assert len(archive_roots) == 1
    archive_root = archive_roots.pop()
    relative_names = {
        name.removeprefix(f"{archive_root}/") for name in names if name != archive_root
    }
    allowed_roots = {
        ".gitignore",
        "LICENSE",
        "src",
        "pyproject.toml",
        "README.md",
        "uv.lock",
        "PKG-INFO",
    }
    assert {name.split("/", 1)[0] for name in relative_names} == allowed_roots
    assert {
        ".gitignore",
        "LICENSE",
        "pyproject.toml",
        "README.md",
        "uv.lock",
        "PKG-INFO",
    } <= relative_names
    forbidden_prefixes = (
        ".agent/",
        ".agents/",
        ".claude/",
        ".codex/",
        ".superpowers/",
        "openspec/",
    )
    assert not any(name.startswith(forbidden_prefixes) for name in relative_names)
    assert "skills-lock.json" not in relative_names
    assert "何为Harness.html" not in relative_names
    required_suffixes = (
        "res/prompts/system.j2",
        "res/prompts/protocol.md",
        "res/prompts/default_soul.md",
    )
    for suffix in required_suffixes:
        assert any(name.endswith(suffix) for name in names), f"{suffix} missing from sdist"

    probe_dir = tmp_path / "wheel-probe"
    probe_dir.mkdir()
    report = probe_dir / "rc-smoke.json"
    subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/m28_release_candidate_smoke.py"),
            "--wheel",
            str(wheels[0]),
            "--output",
            str(report),
            "--python",
            sys.executable,
        ],
        cwd=probe_dir,
        check=True,
        capture_output=True,
        env=_clean_python_environment(uv_env),
    )
    result = json.loads(report.read_text(encoding="utf-8"))
    assert set(result) == {
        "schema",
        "version",
        "python",
        "wheel_sha256",
        "passed",
        "checks",
    }
    assert result["passed"] is True
    assert result["checks"] == dict.fromkeys(
        ("clean-wheel", "cli", "http", "single", "duo", "triad"), "passed"
    )
