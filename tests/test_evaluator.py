"""Contract tests for forgeagent.evaluator isolation and artifact boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import forgeagent.evaluator as evaluator_module
from forgeagent.client import MockClient
from forgeagent.evaluator import (
    EVALUATOR_SYSTEM_PROMPT,
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACTS,
    MAX_TOTAL_ARTIFACT_BYTES,
    ArtifactManifestItem,
    EvaluationRequest,
    EvaluatorPreflightError,
    EvaluatorResult,
    run_evaluator,
    validate_artifact_manifest,
)
from forgeagent.tools import ToolRegistry

VALID_RESULT = (
    "evaluator_result:\n  status: passed\n  observed_evidence: []\n  unmet_expectations: []\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_request(
    tmp_path: Path,
    task_description: str = "check output",
    expected_behavior: str = "file contains ok",
    artifacts: tuple[ArtifactManifestItem, ...] = (),
) -> EvaluationRequest:
    return EvaluationRequest(
        task_description=task_description,
        expected_behavior=expected_behavior,
        artifact_root=tmp_path,
        artifacts=artifacts,
    )


@dataclass
class FakeTask:
    """Minimal Task stand-in for isolation tests."""

    _closed: bool = False
    _outcome_text: str = ""

    def run(self, goal: str, **kwargs: Any) -> Any:
        from forgeagent.step import RoundResult

        @dataclass
        class FakeOutcome:
            rounds: list[RoundResult]

        if self._outcome_text:
            round_ = RoundResult(text=self._outcome_text)
        else:
            round_ = RoundResult(text="")
        return FakeOutcome(rounds=[round_])

    def close(self) -> None:
        self._closed = True


# ---------------------------------------------------------------------------
# 1. validate_artifact_manifest — acceptance
# ---------------------------------------------------------------------------


def test_manifest_accepts_valid_single_file(tmp_path):
    (tmp_path / "ok.txt").write_text("ok", encoding="utf-8")
    result = validate_artifact_manifest(tmp_path, ["ok.txt"])
    assert len(result) == 1
    assert result[0].path == "ok.txt"
    assert result[0].size_bytes == 2


# ---------------------------------------------------------------------------
# 2. validate_artifact_manifest — rejection cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_path",
    [
        "../secret.txt",
        "sub/../../../etc/passwd",
    ],
)
def test_manifest_rejects_path_escape(tmp_path, bad_path):
    with pytest.raises(EvaluatorPreflightError):
        validate_artifact_manifest(tmp_path, [bad_path])


def test_manifest_rejects_absolute_path(tmp_path):
    with pytest.raises(EvaluatorPreflightError):
        validate_artifact_manifest(tmp_path, [str(tmp_path / "ok.txt")])


def test_manifest_rejects_missing_file(tmp_path):
    with pytest.raises(EvaluatorPreflightError):
        validate_artifact_manifest(tmp_path, ["missing.txt"])


def test_manifest_rejects_directory_artifact(tmp_path):
    (tmp_path / "subdir").mkdir()
    with pytest.raises(EvaluatorPreflightError):
        validate_artifact_manifest(tmp_path, ["subdir"])


def test_manifest_rejects_too_many_artifacts(tmp_path):
    paths = []
    for i in range(MAX_ARTIFACTS + 1):
        name = f"f{i}.txt"
        (tmp_path / name).write_text("x", encoding="utf-8")
        paths.append(name)
    with pytest.raises(EvaluatorPreflightError):
        validate_artifact_manifest(tmp_path, paths)


def test_manifest_rejects_oversized_file(tmp_path):
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * (MAX_ARTIFACT_BYTES + 1))
    with pytest.raises(EvaluatorPreflightError):
        validate_artifact_manifest(tmp_path, ["big.bin"])


def test_manifest_rejects_total_size_exceeded(tmp_path):
    # Two files each just over half the total limit
    chunk = MAX_TOTAL_ARTIFACT_BYTES // 2 + 1
    (tmp_path / "a.bin").write_bytes(b"a" * chunk)
    (tmp_path / "b.bin").write_bytes(b"b" * chunk)
    with pytest.raises(EvaluatorPreflightError):
        validate_artifact_manifest(tmp_path, ["a.bin", "b.bin"])


def test_manifest_rejects_control_chars_in_path(tmp_path):
    with pytest.raises(EvaluatorPreflightError):
        validate_artifact_manifest(tmp_path, ["bad\x00name.txt"])


def test_manifest_rejects_symlink_root(tmp_path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real_dir)
    with pytest.raises(EvaluatorPreflightError):
        validate_artifact_manifest(link, [])


def test_manifest_rejects_unreadable_root(monkeypatch, tmp_path):
    monkeypatch.setattr(evaluator_module.os, "access", lambda path, mode: False)

    with pytest.raises(EvaluatorPreflightError):
        validate_artifact_manifest(tmp_path, [])


@pytest.mark.parametrize("bad_path", [r"sub\artifact.txt", "./artifact.txt", "a//b.txt"])
def test_manifest_requires_canonical_relative_posix_paths(tmp_path, bad_path):
    target = tmp_path / bad_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("artifact", encoding="utf-8")

    with pytest.raises(EvaluatorPreflightError):
        validate_artifact_manifest(tmp_path, [bad_path])


# ---------------------------------------------------------------------------
# 3. run_evaluator — Task isolation contract
# ---------------------------------------------------------------------------


def test_evaluator_task_has_no_generator_context(monkeypatch, tmp_path):
    captured: dict = {}
    fake_task = FakeTask(_outcome_text=VALID_RESULT)

    def fake_task_ctor(client, **kw):
        captured.update(kw)
        return fake_task

    monkeypatch.setattr(evaluator_module, "Task", fake_task_ctor)

    run_evaluator(MockClient(script=[]), make_request(tmp_path))

    # Isolation kwargs must be present and set to None
    assert captured.get("tier") == "restricted"
    assert captured.get("allowed_root") == str(tmp_path.resolve())
    assert captured.get("system_prompt") == EVALUATOR_SYSTEM_PROMPT
    assert captured.get("max_rounds") == 2
    assert captured.get("memory_manager") is None
    assert captured.get("skills") is None
    assert captured.get("mcp") is None
    assert captured.get("audit_sink") is None
    # Generator-only params must NOT appear
    assert "identity" not in captured
    assert "asker" not in captured
    assert "confirmer" not in captured


def test_evaluator_registry_contains_only_file_tools(monkeypatch, tmp_path):
    captured: dict = {}
    fake_task = FakeTask(_outcome_text=VALID_RESULT)

    def fake_task_ctor(client, **kw):
        captured.update(kw)
        return fake_task

    monkeypatch.setattr(evaluator_module, "Task", fake_task_ctor)

    run_evaluator(MockClient(script=[]), make_request(tmp_path))

    registry: ToolRegistry = captured.get("tool_registry")
    assert registry is not None, "tool_registry must be passed to Task"
    tool_names = set(registry.arg_schemas().keys())
    assert tool_names == {"FileRead", "FileList"}


# ---------------------------------------------------------------------------
# 4. run_evaluator — Task.close() called on both success and failure
# ---------------------------------------------------------------------------


def test_evaluator_calls_close_on_success(monkeypatch, tmp_path):
    fake_task = FakeTask(_outcome_text=VALID_RESULT)
    monkeypatch.setattr(evaluator_module, "Task", lambda c, **kw: fake_task)

    run_evaluator(MockClient(script=[]), make_request(tmp_path))
    assert fake_task._closed


def test_evaluator_calls_close_on_run_exception(monkeypatch, tmp_path):
    @dataclass
    class FailTask:
        _closed: bool = False

        def run(self, goal: str, **kw: Any) -> Any:
            raise RuntimeError("model exploded")

        def close(self) -> None:
            self._closed = True

    fail_task = FailTask()
    monkeypatch.setattr(evaluator_module, "Task", lambda c, **kw: fail_task)

    result = run_evaluator(MockClient(script=[]), make_request(tmp_path))
    assert fail_task._closed
    assert result.status == "failed"
    assert result.unmet_expectations == ("evaluation unavailable",)


def test_evaluator_returns_safe_failure_when_task_construction_fails(monkeypatch, tmp_path):
    def fail_task_ctor(client, **kwargs):
        raise RuntimeError("provider secret and /absolute/host/path")

    monkeypatch.setattr(evaluator_module, "Task", fail_task_ctor)

    result = run_evaluator(MockClient(script=[]), make_request(tmp_path))

    assert result == EvaluatorResult(
        status="failed",
        observed_evidence=(),
        unmet_expectations=("evaluation unavailable",),
    )


def test_evaluator_revalidates_supplied_manifest_before_creating_task(monkeypatch, tmp_path):
    captured = False

    def fake_task_ctor(client, **kwargs):
        nonlocal captured
        captured = True
        return FakeTask()

    monkeypatch.setattr(evaluator_module, "Task", fake_task_ctor)
    request = make_request(
        tmp_path,
        artifacts=(ArtifactManifestItem(path="../outside.txt", size_bytes=1),),
    )

    result = run_evaluator(MockClient(script=[]), request)

    assert result.status == "failed"
    assert not captured


# ---------------------------------------------------------------------------
# 5. run_evaluator — malformed model result → safe failure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_text",
    [
        "",
        "not yaml at all ::::",
        "evaluator_result:\n  status: maybe\n",
        "evaluator_result: null\n",
        "just: some text\nno_evaluator_result: here\n",
    ],
)
def test_evaluator_returns_failure_for_malformed_result(monkeypatch, tmp_path, bad_text):
    fake_task = FakeTask(_outcome_text=bad_text)
    monkeypatch.setattr(evaluator_module, "Task", lambda c, **kw: fake_task)

    result = run_evaluator(MockClient(script=[]), make_request(tmp_path))
    assert result.status == "failed"
    assert result.unmet_expectations == ("evaluation unavailable",)


@pytest.mark.parametrize(
    "bad_text",
    [
        (
            "evaluator_result:\n"
            "  status: passed\n"
            "  observed_evidence: []\n"
            "  unmet_expectations: []\n"
            "  extra: forbidden\n"
        ),
        (
            "evaluator_result:\n"
            "  status: passed\n"
            "  observed_evidence: [123]\n"
            "  unmet_expectations: []\n"
        ),
        (
            "evaluator_result:\n"
            "  status: passed\n"
            "  observed_evidence: []\n"
            "  unmet_expectations: []\n"
            "top_level_extra: forbidden\n"
        ),
    ],
)
def test_evaluator_rejects_non_exact_result_shape(monkeypatch, tmp_path, bad_text):
    fake_task = FakeTask(_outcome_text=bad_text)
    monkeypatch.setattr(evaluator_module, "Task", lambda c, **kw: fake_task)

    result = run_evaluator(MockClient(script=[]), make_request(tmp_path))

    assert result.status == "failed"
    assert result.unmet_expectations == ("evaluation unavailable",)


# ---------------------------------------------------------------------------
# 6. run_evaluator — valid YAML result is parsed correctly
# ---------------------------------------------------------------------------


def test_evaluator_parses_valid_passed_result(monkeypatch, tmp_path):
    yaml_text = (
        "evaluator_result:\n"
        "  status: passed\n"
        "  observed_evidence:\n"
        "    - file contains expected text\n"
        "  unmet_expectations: []\n"
    )
    fake_task = FakeTask(_outcome_text=yaml_text)
    monkeypatch.setattr(evaluator_module, "Task", lambda c, **kw: fake_task)

    result = run_evaluator(MockClient(script=[]), make_request(tmp_path))
    assert result.status == "passed"
    assert result.observed_evidence == ("file contains expected text",)
    assert result.unmet_expectations == ()


def test_evaluator_parses_valid_failed_result(monkeypatch, tmp_path):
    yaml_text = (
        "evaluator_result:\n"
        "  status: failed\n"
        "  observed_evidence: []\n"
        "  unmet_expectations:\n"
        "    - output file missing\n"
    )
    fake_task = FakeTask(_outcome_text=yaml_text)
    monkeypatch.setattr(evaluator_module, "Task", lambda c, **kw: fake_task)

    result = run_evaluator(MockClient(script=[]), make_request(tmp_path))
    assert result.status == "failed"
    assert result.unmet_expectations == ("output file missing",)


# ---------------------------------------------------------------------------
# 7. Evidence is bounded (truncated at MAX_EVIDENCE_CHARS, capped at MAX_EVIDENCE_ITEMS)
# ---------------------------------------------------------------------------


def test_evaluator_truncates_long_evidence(monkeypatch, tmp_path):
    from forgeagent.evaluator import MAX_EVIDENCE_CHARS

    long_line = "x" * (MAX_EVIDENCE_CHARS + 100)
    yaml_text = (
        "evaluator_result:\n"
        "  status: passed\n"
        f"  observed_evidence:\n    - {long_line}\n"
        "  unmet_expectations: []\n"
    )
    fake_task = FakeTask(_outcome_text=yaml_text)
    monkeypatch.setattr(evaluator_module, "Task", lambda c, **kw: fake_task)

    result = run_evaluator(MockClient(script=[]), make_request(tmp_path))
    assert len(result.observed_evidence[0]) == MAX_EVIDENCE_CHARS


def test_evaluator_caps_evidence_items(monkeypatch, tmp_path):
    from forgeagent.evaluator import MAX_EVIDENCE_ITEMS

    items = "\n".join(f"    - item {i}" for i in range(MAX_EVIDENCE_ITEMS + 5))
    yaml_text = (
        "evaluator_result:\n"
        "  status: passed\n"
        f"  observed_evidence:\n{items}\n"
        "  unmet_expectations: []\n"
    )
    fake_task = FakeTask(_outcome_text=yaml_text)
    monkeypatch.setattr(evaluator_module, "Task", lambda c, **kw: fake_task)

    result = run_evaluator(MockClient(script=[]), make_request(tmp_path))
    assert len(result.observed_evidence) == MAX_EVIDENCE_ITEMS


def test_evaluator_sanitizes_prompt_and_result_text(monkeypatch, tmp_path):
    secret = "evaluator-secret-value"
    absolute_path = "/Users/example/private/artifact.txt"
    captured_goal = ""
    fake_task = FakeTask(
        _outcome_text=(
            "evaluator_result:\n"
            "  status: failed\n"
            f"  observed_evidence: ['found {secret} at {absolute_path}']\n"
            '  unmet_expectations: ["bad\\tvalue"]\n'
        )
    )

    def run_and_capture(goal: str, **kwargs: Any) -> Any:
        nonlocal captured_goal
        captured_goal = goal
        return FakeTask.run(fake_task, goal, **kwargs)

    fake_task.run = run_and_capture  # type: ignore[method-assign]
    monkeypatch.setenv("FORGEAGENT_TEST_SECRET", secret)
    monkeypatch.setattr(evaluator_module, "Task", lambda c, **kw: fake_task)

    result = run_evaluator(
        MockClient(script=[]),
        make_request(
            tmp_path,
            task_description=f"inspect {absolute_path}",
            expected_behavior=f"must not expose {secret}\nnext line",
        ),
    )

    assert secret not in captured_goal
    assert absolute_path not in captured_goal
    assert "\nnext line" not in captured_goal
    assert secret not in repr(result)
    assert absolute_path not in repr(result)
    assert result.unmet_expectations == (r"bad\x09value",)


@pytest.mark.parametrize(
    ("artifact_text", "unmet"),
    [
        ("wrong value", "expected value was absent"),
        ("", "required output was missing"),
        ("unexpected extra data", "output contract was violated"),
    ],
)
def test_known_bad_artifact_fixtures_report_failed(monkeypatch, tmp_path, artifact_text, unmet):
    (tmp_path / "result.txt").write_text(artifact_text, encoding="utf-8")
    artifacts = validate_artifact_manifest(tmp_path, ["result.txt"])
    fake_task = FakeTask(
        _outcome_text=(
            "evaluator_result:\n"
            "  status: failed\n"
            "  observed_evidence: []\n"
            f"  unmet_expectations: ['{unmet}']\n"
        )
    )
    monkeypatch.setattr(evaluator_module, "Task", lambda c, **kw: fake_task)

    result = run_evaluator(MockClient(script=[]), make_request(tmp_path, artifacts=artifacts))

    assert result.status == "failed"
    assert result.unmet_expectations == (unmet,)


# ---------------------------------------------------------------------------
# 8. EvaluatorResult is immutable
# ---------------------------------------------------------------------------


def test_evaluator_result_is_frozen():
    r = EvaluatorResult(status="passed", observed_evidence=(), unmet_expectations=())
    with pytest.raises((AttributeError, TypeError)):
        r.status = "failed"  # type: ignore[misc]
