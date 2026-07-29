from __future__ import annotations

import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "m28_release_candidate_smoke.py"
SPEC = importlib.util.spec_from_file_location("m28_release_candidate_smoke", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def _wheel(path: Path, *, name: str = "forgeagent", version: str = "0.1.0") -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"{name}-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.3\nName: {name}\nVersion: {version}\n",
        )
    return path


def test_clean_environment_removes_import_and_provider_secrets(tmp_path):
    cleaned = smoke.clean_environment(
        {
            "PATH": "/usr/bin",
            "PYTHONHOME": "/source/python",
            "PYTHONPATH": "/source/src",
            "ANTHROPIC_API_KEY": "secret",
            "OPENAI_API_KEY": "secret",
            "LLM_API_KEY": "secret",
            "SAFE_FLAG": "kept",
        },
        tmp_path,
    )

    assert cleaned["HOME"] == str(tmp_path)
    assert cleaned["SAFE_FLAG"] == "kept"
    assert not (
        {"PYTHONHOME", "PYTHONPATH", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LLM_API_KEY"}
        & cleaned.keys()
    )


def test_validate_pip_cache_accepts_private_owned_directory(tmp_path):
    cache = tmp_path / "pip-cache"
    cache.mkdir(mode=0o700)

    smoke.validate_pip_cache({"PIP_CACHE_DIR": str(cache)})


@pytest.mark.parametrize("kind", ["relative", "symlink", "permissive"])
def test_validate_pip_cache_rejects_unsafe_directory(tmp_path, kind):
    cache = tmp_path / "pip-cache"
    cache.mkdir(mode=0o700)
    value = str(cache)
    if kind == "relative":
        value = "relative-cache"
    elif kind == "symlink":
        link = tmp_path / "pip-cache-link"
        link.symlink_to(cache, target_is_directory=True)
        value = str(link)
    else:
        cache.chmod(0o755)

    with pytest.raises(ValueError, match="pip cache must be a private owned directory"):
        smoke.validate_pip_cache({"PIP_CACHE_DIR": value})


def test_wheel_identity_validates_metadata_and_returns_sha256(tmp_path):
    wheel = _wheel(tmp_path / "forgeagent-0.1.0-py3-none-any.whl")

    version, digest = smoke.wheel_identity(wheel)

    assert version == "0.1.0"
    assert re.fullmatch(r"[0-9a-f]{64}", digest)


@pytest.mark.parametrize(
    ("name", "version"),
    [("other", "0.1.0"), ("forgeagent", "0.2.0")],
)
def test_wheel_identity_rejects_wrong_name_or_version(tmp_path, name, version):
    wheel = _wheel(tmp_path / "candidate.whl", name=name, version=version)

    with pytest.raises(ValueError, match="wheel metadata is invalid"):
        smoke.wheel_identity(wheel)


def test_wheel_identity_rejects_multiple_metadata_files(tmp_path):
    wheel = _wheel(tmp_path / "candidate.whl")
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr(
            "duplicate-0.1.0.dist-info/METADATA",
            "Metadata-Version: 2.3\nName: forgeagent\nVersion: 0.1.0\n",
        )

    with pytest.raises(ValueError, match="wheel metadata is invalid"):
        smoke.wheel_identity(wheel)


def test_wheel_identity_rejects_non_regular_file(tmp_path):
    candidate = tmp_path / "candidate.whl"
    candidate.mkdir()

    with pytest.raises(ValueError, match="wheel must be a regular file"):
        smoke.wheel_identity(candidate)


def test_wheel_identity_rejects_symlink(tmp_path):
    wheel = _wheel(tmp_path / "candidate.whl")
    link = tmp_path / "linked.whl"
    link.symlink_to(wheel)

    with pytest.raises(ValueError, match="wheel must be a regular file"):
        smoke.wheel_identity(link)


def test_write_report_is_complete_and_bounded(tmp_path):
    report = smoke.new_report("a" * 64)
    report["checks"] = dict.fromkeys(smoke.CHECK_NAMES, "passed")
    smoke.finalize_report(report)
    output = tmp_path / "report.json"

    smoke.write_report(output, report)

    loaded = json.loads(output.read_text())
    assert loaded["schema"] == "forgeagent.release-candidate-smoke/v1"
    assert loaded["version"] == "0.1.0"
    assert loaded["passed"] is True
    assert set(loaded["checks"]) == set(smoke.CHECK_NAMES)
    assert set(loaded) == {"schema", "version", "python", "wheel_sha256", "passed", "checks"}
    assert "secret" not in output.read_text()


def test_new_report_starts_all_checks_not_run():
    report = smoke.new_report("a" * 64)

    assert report["passed"] is False
    assert report["checks"] == dict.fromkeys(smoke.CHECK_NAMES, "not-run")


def test_finalize_report_requires_every_check_to_pass():
    report = smoke.new_report("a" * 64)
    report["checks"]["clean-wheel"] = "passed"

    smoke.finalize_report(report)

    assert report["passed"] is False


def test_write_report_flushes_and_fsyncs_before_same_directory_replace(tmp_path, monkeypatch):
    output = tmp_path / "report.json"
    report = smoke.new_report("a" * 64)
    events = []
    original_named_temporary_file = smoke.tempfile.NamedTemporaryFile
    original_replace = smoke.os.replace

    class RecordingFile:
        def __init__(self, handle):
            self._handle = handle

        def __getattr__(self, name):
            return getattr(self._handle, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self._handle.__exit__(*args)

        def flush(self):
            events.append("flush")
            return self._handle.flush()

    def recording_temporary_file(*args, **kwargs):
        return RecordingFile(original_named_temporary_file(*args, **kwargs))

    def recording_fsync(file_descriptor):
        events.append("fsync")
        assert stat.S_ISREG(os.fstat(file_descriptor).st_mode)

    def recording_replace(source, target):
        events.append("replace")
        assert Path(source).parent == output.parent
        assert Path(target) == output
        original_replace(source, target)

    monkeypatch.setattr(smoke.tempfile, "NamedTemporaryFile", recording_temporary_file)
    monkeypatch.setattr(smoke.os, "fsync", recording_fsync)
    monkeypatch.setattr(smoke.os, "replace", recording_replace)

    smoke.write_report(output, report)

    assert events == ["flush", "fsync", "replace"]
    assert json.loads(output.read_text())["schema"] == smoke.SCHEMA


def test_write_report_removes_temporary_file_when_replace_fails(tmp_path, monkeypatch):
    output = tmp_path / "report.json"

    def fail_replace(_source, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(smoke.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        smoke.write_report(output, smoke.new_report("a" * 64))

    assert list(tmp_path.iterdir()) == []


def test_cli_check_uses_console_script_and_builtin_models(tmp_path):
    console = Path(sys.executable).parent / ("forgeagent.exe" if os.name == "nt" else "forgeagent")

    smoke.check_cli(console, smoke.clean_environment(os.environ, tmp_path))


def test_http_check_uses_real_loopback_and_closes():
    baseline_threads = set(smoke.threading.enumerate())

    smoke.check_http()

    assert [
        thread for thread in smoke.threading.enumerate() if thread not in baseline_threads
    ] == []


def test_http_check_ignores_hostile_proxy_environment(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")

    smoke.check_http()


@pytest.mark.parametrize("mode", ["single", "duo", "triad"])
def test_collaboration_checks_complete_without_provider(mode, tmp_path):
    report = smoke.check_collaboration(mode, tmp_path)

    assert report == {"mode": mode, "status": "completed"}


def test_run_installed_marks_clean_wheel_failed_without_running_later_checks(
    tmp_path, monkeypatch, capsys
):
    output = tmp_path / "report.json"
    monkeypatch.setattr(smoke.importlib.metadata, "version", lambda _name: "0.2.0")
    monkeypatch.setattr(
        smoke,
        "check_cli",
        lambda *_args: pytest.fail("CLI must remain not-run after clean-wheel failure"),
        raising=False,
    )

    status = smoke.run_installed(output, "a" * 64)

    report = json.loads(output.read_text())
    assert status == 1
    assert report["passed"] is False
    assert report["checks"] == {
        "clean-wheel": "failed",
        "cli": "not-run",
        "http": "not-run",
        "single": "not-run",
        "duo": "not-run",
        "triad": "not-run",
    }
    assert capsys.readouterr().err == "M28 RC smoke failed: clean-wheel\n"


def test_run_parent_uses_bounded_isolated_subprocesses(tmp_path, monkeypatch):
    wheel = _wheel(tmp_path / "forgeagent-0.1.0-py3-none-any.whl")
    output = tmp_path / "report.json"
    calls = []
    monkeypatch.setenv("PYTHONHOME", "/source/python")
    monkeypatch.setenv("PYTHONPATH", "/source/src")
    monkeypatch.setenv("OPENAI_API_KEY", "private")
    monkeypatch.delenv("PIP_CACHE_DIR", raising=False)

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        assert kwargs["shell"] is False
        assert kwargs["capture_output"] is True
        expected_timeout = 600 if argv[1:4] == ["-m", "pip", "install"] else 180
        assert kwargs["timeout"] == expected_timeout
        if "--installed" in argv:
            child_output = Path(argv[argv.index("--output") + 1])
            report = smoke.new_report(argv[argv.index("--wheel-sha256") + 1])
            report["checks"] = dict.fromkeys(smoke.CHECK_NAMES, "passed")
            smoke.finalize_report(report)
            smoke.write_report(child_output, report)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)

    status = smoke.run_parent(wheel, output, sys.executable)

    assert status == 0
    assert json.loads(output.read_text())["passed"] is True
    assert len(calls) == 3
    assert calls[0][0][:3] == [sys.executable, "-m", "venv"]
    venv_python = calls[1][0][0]
    assert calls[1][0][:4] == [venv_python, "-m", "pip", "install"]
    child_argv, child_kwargs = calls[2]
    assert child_argv[:2] == [venv_python, "-I"]
    assert child_argv[2] == str(SCRIPT.resolve())
    assert "--installed" in child_argv
    assert Path(child_kwargs["cwd"]).name == "probe"
    expected_home = str(Path(child_kwargs["cwd"]).parent / "home")
    for _argv, kwargs in calls:
        assert kwargs["env"]["HOME"] == expected_home
        assert not ({"PYTHONHOME", "PYTHONPATH", "OPENAI_API_KEY"} & kwargs["env"].keys())
    assert "PIP_CACHE_DIR" not in calls[1][1]["env"]


def test_run_parent_installs_the_validated_snapshot(tmp_path, monkeypatch):
    wheel = _wheel(tmp_path / "forgeagent-0.1.0-py3-none-any.whl")
    _, expected_digest = smoke.wheel_identity(wheel)
    output = tmp_path / "report.json"

    def fake_run(argv, **_kwargs):
        if argv[1:3] == ["-m", "venv"]:
            _wheel(wheel, name="replaced")
        elif argv[1:4] == ["-m", "pip", "install"]:
            installed_wheel = Path(argv[4])
            assert installed_wheel != wheel.resolve()
            assert installed_wheel.parent.name.startswith("forgeagent-m28-rc-")
            assert smoke.wheel_identity(installed_wheel) == ("0.1.0", expected_digest)
        elif "--installed" in argv:
            assert argv[argv.index("--wheel-sha256") + 1] == expected_digest
            report = smoke.new_report(expected_digest)
            report["checks"] = dict.fromkeys(smoke.CHECK_NAMES, "passed")
            smoke.finalize_report(report)
            smoke.write_report(output, report)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)

    assert smoke.run_parent(wheel, output, sys.executable) == 0
    assert json.loads(output.read_text())["wheel_sha256"] == expected_digest


def test_run_parent_rejects_invalid_wheel_with_bounded_report(tmp_path, capsys):
    wheel = tmp_path / "invalid.whl"
    wheel.write_text("not a wheel")
    output = tmp_path / "report.json"

    status = smoke.run_parent(wheel, output, sys.executable)

    report = json.loads(output.read_text())
    assert status == 1
    assert report["checks"] == {
        "clean-wheel": "failed",
        "cli": "not-run",
        "http": "not-run",
        "single": "not-run",
        "duo": "not-run",
        "triad": "not-run",
    }
    assert report["passed"] is False
    assert capsys.readouterr().err == "M28 RC smoke failed: clean-wheel\n"


def test_run_parent_bounds_nonzero_child_as_clean_wheel_failure(tmp_path, monkeypatch, capsys):
    wheel = _wheel(tmp_path / "forgeagent-0.1.0-py3-none-any.whl")
    output = tmp_path / "report.json"

    def fake_run(argv, **kwargs):
        assert kwargs["capture_output"] is True
        if "--installed" not in argv:
            return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")
        report = smoke.new_report("a" * 64)
        report["checks"]["clean-wheel"] = "passed"
        report["checks"]["cli"] = "failed"
        smoke.write_report(output, report)
        return subprocess.CompletedProcess(argv, 1, stdout=b"private", stderr=b"secret")

    monkeypatch.setattr(smoke, "wheel_identity", lambda _wheel: ("0.1.0", "a" * 64))
    monkeypatch.setattr(smoke.subprocess, "run", fake_run)

    status = smoke.run_parent(wheel, output, sys.executable)

    assert status == 1
    assert json.loads(output.read_text())["checks"] == {
        "clean-wheel": "failed",
        "cli": "not-run",
        "http": "not-run",
        "single": "not-run",
        "duo": "not-run",
        "triad": "not-run",
    }
    assert capsys.readouterr().err == "M28 RC smoke failed: clean-wheel\n"


def test_run_parent_never_keeps_passed_report_after_child_failure(tmp_path, monkeypatch):
    wheel = _wheel(tmp_path / "forgeagent-0.1.0-py3-none-any.whl")
    output = tmp_path / "report.json"

    def fake_run(argv, **_kwargs):
        if "--installed" in argv:
            report = smoke.new_report("a" * 64)
            report["checks"] = dict.fromkeys(smoke.CHECK_NAMES, "passed")
            smoke.finalize_report(report)
            smoke.write_report(output, report)
            return subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"")
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(smoke, "wheel_identity", lambda _wheel: ("0.1.0", "a" * 64))
    monkeypatch.setattr(smoke.subprocess, "run", fake_run)

    assert smoke.run_parent(wheel, output, sys.executable) == 1
    report = json.loads(output.read_text())
    assert report["passed"] is False
    assert report["checks"] == {
        "clean-wheel": "failed",
        "cli": "not-run",
        "http": "not-run",
        "single": "not-run",
        "duo": "not-run",
        "triad": "not-run",
    }


def test_run_parent_rejects_contradictory_zero_exit_report(tmp_path, monkeypatch, capsys):
    wheel = _wheel(tmp_path / "forgeagent-0.1.0-py3-none-any.whl")
    output = tmp_path / "report.json"

    def fake_run(argv, **_kwargs):
        if "--installed" in argv:
            report = smoke.new_report("a" * 64)
            report["checks"] = dict.fromkeys(smoke.CHECK_NAMES, "passed")
            report["checks"]["cli"] = "failed"
            smoke.finalize_report(report)
            smoke.write_report(output, report)
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(smoke, "wheel_identity", lambda _wheel: ("0.1.0", "a" * 64))
    monkeypatch.setattr(smoke.subprocess, "run", fake_run)

    assert smoke.run_parent(wheel, output, sys.executable) == 1
    report = json.loads(output.read_text())
    assert report["passed"] is False
    assert report["checks"] == {
        "clean-wheel": "failed",
        "cli": "not-run",
        "http": "not-run",
        "single": "not-run",
        "duo": "not-run",
        "triad": "not-run",
    }
    assert capsys.readouterr().err == "M28 RC smoke failed: clean-wheel\n"


@pytest.mark.parametrize(
    ("mutation"),
    [
        pytest.param(lambda report: report.pop("version"), id="missing-required-key"),
        pytest.param(lambda report: report.__setitem__("unexpected", True), id="unexpected-key"),
        pytest.param(lambda report: report.__setitem__("version", "0.2.0"), id="wrong-version"),
        pytest.param(lambda report: report.pop("python"), id="missing-python"),
        pytest.param(lambda report: report.__setitem__("python", "3.11"), id="malformed-python"),
        pytest.param(
            lambda report: report.__setitem__("python", "3.10.14"),
            id="unsupported-python",
        ),
    ],
)
def test_run_parent_rejects_malformed_zero_exit_report(tmp_path, monkeypatch, mutation):
    wheel = _wheel(tmp_path / "forgeagent-0.1.0-py3-none-any.whl")
    output = tmp_path / "report.json"

    def fake_run(argv, **_kwargs):
        if "--installed" in argv:
            report = smoke.new_report("a" * 64)
            report["checks"] = dict.fromkeys(smoke.CHECK_NAMES, "passed")
            smoke.finalize_report(report)
            mutation(report)
            smoke.write_report(output, report)
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(smoke, "wheel_identity", lambda _wheel: ("0.1.0", "a" * 64))
    monkeypatch.setattr(smoke.subprocess, "run", fake_run)

    assert smoke.run_parent(wheel, output, sys.executable) == 1
    report = json.loads(output.read_text())
    assert report["passed"] is False
    assert report["checks"] == {
        "clean-wheel": "failed",
        "cli": "not-run",
        "http": "not-run",
        "single": "not-run",
        "duo": "not-run",
        "triad": "not-run",
    }


def test_main_routes_public_and_private_modes(monkeypatch, tmp_path):
    wheel = tmp_path / "candidate.whl"
    output = tmp_path / "report.json"
    calls = []
    monkeypatch.setattr(
        smoke,
        "run_parent",
        lambda wheel, output, python: calls.append((wheel, output, python)) or 7,
    )
    monkeypatch.setattr(
        smoke,
        "run_installed",
        lambda output, digest: calls.append((output, digest)) or 8,
    )

    assert (
        smoke.main(["--wheel", str(wheel), "--output", str(output), "--python", sys.executable])
        == 7
    )
    assert smoke.main(["--installed", "--output", str(output), "--wheel-sha256", "a" * 64]) == 8
    assert calls == [(wheel, output, sys.executable), (output, "a" * 64)]
