"""Packaging regression for runtime identity prompt resources."""

from __future__ import annotations

import os
import subprocess
import tarfile
from pathlib import Path


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
    result = subprocess.run(
        [
            str(venv_python),
            "-c",
            "from forgeagent.identity import ApprovedIdentity, compose_system_prompt\n"
            "rendered = compose_system_prompt(ApprovedIdentity(soul=None, user=None, "
            "project_agents=None, memory=None))\n"
            "assert 'No custom Agent Identity (SOUL)' in rendered\n"
            "assert 'This conversation is driven by ForgeAgent' in rendered\n"
            "print('OK')\n",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "OK"
