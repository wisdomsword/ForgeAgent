"""Packaging regression for runtime identity prompt resources."""

from __future__ import annotations

import os
import subprocess
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


def test_wheel_and_sdist_contain_prompt_resources(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    dist_dir = tmp_path / "dist"
    uv_env = os.environ.copy()
    uv_env.setdefault("UV_CACHE_DIR", str(tmp_path / "uv-cache"))
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
    archive_root = names[0].split("/", 1)[0]
    relative_names = {
        name.removeprefix(f"{archive_root}/") for name in names if name != archive_root
    }
    allowed_roots = {
        ".gitignore",
        "src",
        "pyproject.toml",
        "README.md",
        "uv.lock",
        "PKG-INFO",
    }
    assert {name.split("/", 1)[0] for name in relative_names} == allowed_roots
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

    venv_dir = tmp_path / "install-venv"
    subprocess.run(
        ["uv", "venv", str(venv_dir), "--python", "3.11"],
        check=True,
        capture_output=True,
        env=uv_env,
    )
    venv_python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        ["uv", "pip", "install", "--python", str(venv_python), str(wheels[0])],
        check=True,
        capture_output=True,
        env=uv_env,
    )
    probe_dir = tmp_path / "wheel-probe"
    probe_dir.mkdir()
    result = subprocess.run(
        [
            str(venv_python),
            "-I",
            "-c",
            "from pathlib import Path\n"
            "import sys\n"
            "import forgeagent\n"
            "from forgeagent.identity import ApprovedIdentity, compose_system_prompt\n"
            "module_path = Path(forgeagent.__file__).resolve()\n"
            "venv_path = Path(sys.prefix).resolve()\n"
            "assert module_path.is_relative_to(venv_path), (module_path, venv_path)\n"
            "rendered = compose_system_prompt(ApprovedIdentity(soul=None, user=None, "
            "project_agents=None, memory=None))\n"
            "assert 'No custom Agent Identity (SOUL)' in rendered\n"
            "assert 'This conversation is driven by ForgeAgent' in rendered\n"
            "print('OK')\n",
        ],
        cwd=probe_dir,
        check=True,
        capture_output=True,
        text=True,
        env=_clean_python_environment(os.environ),
    )
    assert result.stdout.strip() == "OK"
