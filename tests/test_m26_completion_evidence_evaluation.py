import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from forgeagent.models import ClientError

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "m26_completion_evidence_evaluation.py"
PROTOCOL = ROOT / "docs" / "evaluation" / "m26" / "protocol.json"


def _load_harness():
    spec = importlib.util.spec_from_file_location("m26_completion_evidence_evaluation", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _evaluation_root(tmp_path: Path) -> Path:
    root = tmp_path / "docs" / "evaluation"
    for milestone in ("m23", "m25"):
        directory = root / milestone
        directory.mkdir(parents=True)
        (directory / "protocol.json").write_text(f'{{"milestone":"{milestone}"}}\n')
    (root / "m26" / "runs").mkdir(parents=True)
    return root


def _protocol_copy(tmp_path: Path, mutate) -> Path:
    value = json.loads(PROTOCOL.read_text())
    mutate(value)
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(value))
    return path


def _rehash_evidence(harness, output: Path) -> None:
    environment_path = output / "environment.json"
    summary_path = output / "summary.json"
    environment = json.loads(environment_path.read_text())
    summary = json.loads(summary_path.read_text())
    environment_sha = hashlib.sha256(harness._canonical(environment)).hexdigest()
    summary["environment_sha256"] = environment_sha
    raw_hashes = {}
    for path in sorted((output / "raw").glob("*.json")):
        record = json.loads(path.read_text())
        record["environment_sha256"] = environment_sha
        content = harness._canonical(record)
        path.write_bytes(content)
        raw_hashes[path.name] = hashlib.sha256(content).hexdigest()
    summary["raw_sha256"] = raw_hashes
    environment_path.write_bytes(harness._canonical(environment))
    summary_path.write_bytes(harness._canonical(summary))
    (output / "report.md").write_text(harness._report(summary))


def test_protocol_has_exact_completion_evidence_matrix() -> None:
    harness = _load_harness()

    protocol = harness.load_protocol(PROTOCOL)
    schedule = harness.build_schedule(protocol)

    assert [(run.mode, run.scenario) for run in schedule] == [
        ("duo", "skip-check-first"),
        ("duo", "all-pass"),
        ("triad", "skip-check-first"),
        ("triad", "all-pass"),
    ]
    assert protocol.fixture.files == {
        "increment.py": "def increment(value):\n    return value + 1\n",
        "test_increment.py": (
            "from increment import increment\n\n\n"
            "def test_increment():\n"
            "    assert increment(1) == 2\n"
        ),
    }
    assert protocol.check.id == "fixture-pytest"
    assert protocol.check.command == ("{python}", "-m", "pytest", "-q", "test_increment.py")


@pytest.mark.parametrize(
    "field,name",
    [
        ("files", "/absolute.py"),
        ("files", "../escape.py"),
        ("files", "nested/../../escape.py"),
        ("required_candidate_files", "/absolute.py"),
        ("required_candidate_files", "../escape.py"),
        ("required_candidate_files", "nested/../../escape.py"),
    ],
)
def test_protocol_rejects_unsafe_fixture_paths(tmp_path: Path, field: str, name: str) -> None:
    harness = _load_harness()

    def mutate(value):
        if field == "files":
            value["fixture"][field][name] = "content"
        else:
            value["fixture"][field].append(name)

    with pytest.raises(ValueError, match="fixture path"):
        harness.load_protocol(_protocol_copy(tmp_path, mutate))


def test_fixture_write_rejects_symlink_parent(tmp_path: Path) -> None:
    harness = _load_harness()
    protocol = harness.load_protocol(
        _protocol_copy(
            tmp_path,
            lambda value: value["fixture"]["files"].update({"nested/value.py": "safe\n"}),
        )
    )
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (fixture_root / "nested").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="fixture path"):
        harness._write_fixture_files(fixture_root, protocol.fixture.files)

    assert not (outside / "value.py").exists()


@pytest.mark.parametrize("milestone", ["m23", "m25"])
def test_output_validation_rejects_other_milestones(tmp_path: Path, milestone: str) -> None:
    harness = _load_harness()
    evaluation_root = _evaluation_root(tmp_path)

    with pytest.raises(ValueError, match="M26 runs root"):
        harness.validate_output_dir(
            evaluation_root / milestone / "runs" / "wrong",
            evaluation_root=evaluation_root,
        )


def test_output_validation_rejects_external_and_symlink_paths(tmp_path: Path) -> None:
    harness = _load_harness()
    evaluation_root = _evaluation_root(tmp_path)

    with pytest.raises(ValueError, match="M26 runs root"):
        harness.validate_output_dir(tmp_path / "outside", evaluation_root=evaluation_root)

    target = tmp_path / "outside-target"
    target.mkdir()
    link = evaluation_root / "m26" / "runs" / "linked"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        harness.validate_output_dir(link, evaluation_root=evaluation_root)


def test_controlled_run_uses_real_runner_checks_and_both_sequences(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _load_harness()
    evaluation_root = _evaluation_root(tmp_path)
    seen_checks: list[tuple[str, ...]] = []
    original_create = harness.CollaborationRunner.create

    def recording_create(**kwargs):
        checks = kwargs["evaluator_checks"]
        seen_checks.append(tuple(checks))
        assert checks["fixture-pytest"].argv[1:] == (
            "-m",
            "pytest",
            "-q",
            "test_increment.py",
        )
        return original_create(**kwargs)

    monkeypatch.setattr(harness.CollaborationRunner, "create", recording_create)

    result = harness.run_evaluation(
        PROTOCOL,
        evaluation_root / "m26" / "runs" / "controlled",
        execution="controlled",
        evaluation_root=evaluation_root,
        repo_root=ROOT,
    )

    assert result["run_count"] == 4
    assert seen_checks == [("fixture-pytest",)] * 4
    raw = [
        json.loads(path.read_text())
        for path in sorted((evaluation_root / "m26" / "runs" / "controlled" / "raw").glob("*.json"))
    ]
    assert [record["scenario"] for record in raw] == [
        "skip-check-first",
        "all-pass",
        "skip-check-first",
        "all-pass",
    ]
    assert all(record["status"] == "completed" for record in raw)
    skipped = [record for record in raw if record["scenario"] == "skip-check-first"]
    direct = [record for record in raw if record["scenario"] == "all-pass"]
    assert all(record["failed_submit_before_check"] is True for record in skipped)
    assert all(record["check_before_successful_submit"] is True for record in skipped)
    assert all(record["failed_submit_before_check"] is False for record in direct)
    assert all(record["check_before_successful_submit"] is True for record in direct)


def test_auto_records_stable_controlled_fallback_without_claiming_real(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _load_harness()
    evaluation_root = _evaluation_root(tmp_path)

    def unavailable_registry():
        raise harness.RegistryError("credential is unavailable at /private/secret")

    monkeypatch.setattr(harness, "load_registry", unavailable_registry)

    result = harness.run_evaluation(
        PROTOCOL,
        evaluation_root / "m26" / "runs" / "fallback",
        execution="auto",
        evaluation_root=evaluation_root,
        repo_root=ROOT,
    )

    assert result["execution"] == "controlled"
    assert result["fallback_reason"] == "registry_unavailable"
    environment = json.loads(
        (evaluation_root / "m26" / "runs" / "fallback" / "environment.json").read_text()
    )
    assert environment["execution"] == "controlled"
    assert environment["fallback_reason"] == "registry_unavailable"
    assert environment["real_execution"] is False


def test_auto_falls_back_when_real_provider_run_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _load_harness()
    evaluation_root = _evaluation_root(tmp_path)
    calls: list[str] = []
    original_run_records = harness._run_records

    monkeypatch.setattr(harness, "load_registry", lambda: object())

    def run_records(protocol, *, execution, registry=None):
        calls.append(execution)
        if execution == "real":
            raise harness.ProviderUnavailable("client_error:network")
        return original_run_records(protocol, execution="controlled")

    monkeypatch.setattr(harness, "_run_records", run_records)

    result = harness.run_evaluation(
        PROTOCOL,
        evaluation_root / "m26" / "runs" / "provider-fallback",
        execution="auto",
        evaluation_root=evaluation_root,
        repo_root=ROOT,
    )

    assert calls == ["real", "controlled"]
    assert result["execution"] == "controlled"
    assert result["fallback_reason"] == "provider_unavailable"


def test_invalid_request_is_provider_unavailable_for_auto_but_not_real(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _load_harness()
    protocol = harness.load_protocol(PROTOCOL)
    fixture_root = tmp_path / "direct-fixture"
    fixture_root.mkdir()
    invalid = ClientError(message="unsupported", kind="invalid_request", attempts=1)

    with pytest.raises(harness.ProviderUnavailable, match="invalid_request"):
        harness._run_one(
            protocol,
            harness.RunSpec(mode="duo", scenario="all-pass"),
            client_factory=lambda _role, _attempt: harness.MockClient([invalid]),
            fixture_root=fixture_root,
        )

    evaluation_root = _evaluation_root(tmp_path)
    original_run_records = harness._run_records
    monkeypatch.setattr(harness, "load_registry", lambda: object())

    def run_records(protocol, *, execution, registry=None):
        if execution == "real":
            raise harness.ProviderUnavailable("client_error:invalid_request")
        return original_run_records(protocol, execution="controlled")

    monkeypatch.setattr(harness, "_run_records", run_records)
    automatic = harness.run_evaluation(
        PROTOCOL,
        evaluation_root / "m26" / "runs" / "invalid-request-auto",
        execution="auto",
        evaluation_root=evaluation_root,
        repo_root=ROOT,
    )
    assert automatic["execution"] == "controlled"
    assert automatic["fallback_reason"] == "provider_unavailable"

    with pytest.raises(harness.ProviderUnavailable, match="invalid_request"):
        harness.run_evaluation(
            PROTOCOL,
            evaluation_root / "m26" / "runs" / "invalid-request-real",
            execution="real",
            evaluation_root=evaluation_root,
            repo_root=ROOT,
        )


def test_existing_evidence_reuse_respects_requested_execution(tmp_path: Path) -> None:
    harness = _load_harness()
    evaluation_root = _evaluation_root(tmp_path)
    output = evaluation_root / "m26" / "runs" / "execution-reuse"
    controlled = harness.run_evaluation(
        PROTOCOL,
        output,
        execution="controlled",
        evaluation_root=evaluation_root,
        repo_root=ROOT,
    )

    assert (
        harness.run_evaluation(
            PROTOCOL,
            output,
            execution="controlled",
            evaluation_root=evaluation_root,
            repo_root=ROOT,
        )
        == controlled
    )
    assert (
        harness.run_evaluation(
            PROTOCOL,
            output,
            execution="auto",
            evaluation_root=evaluation_root,
            repo_root=ROOT,
        )
        == controlled
    )
    with pytest.raises(FileExistsError, match="execution"):
        harness.run_evaluation(
            PROTOCOL,
            output,
            execution="real",
            evaluation_root=evaluation_root,
            repo_root=ROOT,
        )


def test_outputs_are_safe_complete_and_hash_bound(tmp_path: Path) -> None:
    harness = _load_harness()
    evaluation_root = _evaluation_root(tmp_path)
    output = evaluation_root / "m26" / "runs" / "safe"

    result = harness.run_evaluation(
        PROTOCOL,
        output,
        execution="controlled",
        evaluation_root=evaluation_root,
        repo_root=ROOT,
    )

    assert sorted(path.name for path in output.iterdir()) == [
        "environment.json",
        "raw",
        "report.md",
        "summary.json",
    ]
    assert len(list((output / "raw").glob("*.json"))) == 4
    assert harness.verify_evidence(output) == result
    forbidden = (
        "prompt",
        "reply",
        "argv",
        "stdout",
        "stderr",
        "snapshot_digest",
        "credential",
        "api_key",
        "base_url",
        str(tmp_path),
    )
    persisted = "\n".join(path.read_text() for path in output.rglob("*") if path.is_file())
    assert all(value not in persisted for value in forbidden)


def test_verify_rejects_semantically_tampered_raw_with_updated_hash(tmp_path: Path) -> None:
    harness = _load_harness()
    evaluation_root = _evaluation_root(tmp_path)
    output = evaluation_root / "m26" / "runs" / "tampered"
    harness.run_evaluation(
        PROTOCOL,
        output,
        execution="controlled",
        evaluation_root=evaluation_root,
        repo_root=ROOT,
    )
    raw = output / "raw" / "01-duo-skip-check-first.json"
    record = json.loads(raw.read_text())
    record["status"] = "failed"
    content = harness._canonical(record)
    raw.write_bytes(content)
    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary["raw_sha256"][raw.name] = hashlib.sha256(content).hexdigest()
    summary_path.write_bytes(harness._canonical(summary))

    with pytest.raises(ValueError, match="raw sequence contract"):
        harness.verify_evidence(output)


@pytest.mark.parametrize(
    "mutation,error",
    [
        (lambda env, summary, raw: env.update(schema="wrong"), "environment schema"),
        (lambda env, summary, raw: summary.update(schema="wrong"), "summary schema"),
        (lambda env, summary, raw: raw.update(schema="wrong"), "raw schema"),
        (lambda env, summary, raw: env.update(unexpected=True), "environment schema"),
        (lambda env, summary, raw: summary.update(unexpected=True), "summary schema"),
        (lambda env, summary, raw: raw.update(unexpected=True), "raw schema"),
        (lambda env, summary, raw: summary.update(execution="real"), "execution mismatch"),
        (lambda env, summary, raw: raw.update(execution="real"), "raw execution"),
        (lambda env, summary, raw: env.update(real_execution=True), "execution metadata"),
        (lambda env, summary, raw: env.update(fallback_reason="provider_unavailable"), "fallback"),
        (
            lambda env, summary, raw: summary.update(fallback_reason="provider_unavailable"),
            "fallback",
        ),
        (lambda env, summary, raw: env.update(protocol_sha256="0" * 64), "protocol hash"),
        (lambda env, summary, raw: summary.update(protocol_sha256="1" * 64), "protocol hash"),
        (lambda env, summary, raw: env.update(runtime_sha256=None), "runtime hash"),
        (
            lambda env, summary, raw: env.update(runtime_sha256={"other.py": "0" * 64}),
            "runtime hash",
        ),
        (
            lambda env, summary, raw: env["runtime_sha256"].update(
                {"src/forgeagent/collaboration.py": "not-a-sha"}
            ),
            "runtime hash",
        ),
    ],
)
def test_verify_rejects_coherently_rehashed_contract_tampering(
    tmp_path: Path, mutation, error: str
) -> None:
    harness = _load_harness()
    evaluation_root = _evaluation_root(tmp_path)
    output = evaluation_root / "m26" / "runs" / f"contract-{error.replace(' ', '-')}"
    harness.run_evaluation(
        PROTOCOL,
        output,
        execution="controlled",
        evaluation_root=evaluation_root,
        repo_root=ROOT,
    )
    environment_path = output / "environment.json"
    summary_path = output / "summary.json"
    raw_path = output / "raw" / "01-duo-skip-check-first.json"
    environment = json.loads(environment_path.read_text())
    summary = json.loads(summary_path.read_text())
    raw = json.loads(raw_path.read_text())
    mutation(environment, summary, raw)
    environment_path.write_bytes(harness._canonical(environment))
    summary_path.write_bytes(harness._canonical(summary))
    raw_path.write_bytes(harness._canonical(raw))
    _rehash_evidence(harness, output)

    with pytest.raises(ValueError, match=error):
        harness.verify_evidence(output)


def test_environment_contains_frozen_safe_identity_fields(tmp_path: Path) -> None:
    harness = _load_harness()
    evaluation_root = _evaluation_root(tmp_path)
    output = evaluation_root / "m26" / "runs" / "environment-fields"

    harness.run_evaluation(
        PROTOCOL,
        output,
        execution="controlled",
        evaluation_root=evaluation_root,
        repo_root=ROOT,
    )

    environment = json.loads((output / "environment.json").read_text())
    assert set(
        (
            "generated_at",
            "git_commit",
            "tracked_dirty",
            "package_version",
            "harness_sha256",
            "runtime_sha256",
        )
    ) <= set(environment)
    assert environment["git_commit"] == harness._git_value(ROOT, "rev-parse", "HEAD")
    assert isinstance(environment["tracked_dirty"], bool)
    assert len(environment["harness_sha256"]) == 64
    assert environment["runtime_sha256"] == {
        "src/forgeagent/check_runner.py": hashlib.sha256(
            (ROOT / "src/forgeagent/check_runner.py").read_bytes()
        ).hexdigest(),
        "src/forgeagent/collaboration.py": hashlib.sha256(
            (ROOT / "src/forgeagent/collaboration.py").read_bytes()
        ).hexdigest(),
    }


def test_rerun_is_idempotent_and_rejects_different_existing_content(tmp_path: Path) -> None:
    harness = _load_harness()
    evaluation_root = _evaluation_root(tmp_path)
    output = evaluation_root / "m26" / "runs" / "repeatable"
    first = harness.run_evaluation(
        PROTOCOL,
        output,
        execution="controlled",
        evaluation_root=evaluation_root,
        repo_root=ROOT,
    )
    before = {
        path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()
    }

    second = harness.run_evaluation(
        PROTOCOL,
        output,
        execution="controlled",
        evaluation_root=evaluation_root,
        repo_root=ROOT,
    )

    assert second == first
    assert {
        path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()
    } == before
    (output / "summary.json").write_text("{}\n")
    with pytest.raises(FileExistsError, match="different content"):
        harness.run_evaluation(
            PROTOCOL,
            output,
            execution="controlled",
            evaluation_root=evaluation_root,
            repo_root=ROOT,
        )


def test_atomic_write_ignores_precreated_temp_symlink(tmp_path: Path) -> None:
    harness = _load_harness()
    target = tmp_path / "summary.json"
    outside = tmp_path / "outside"
    outside.write_text("unchanged")
    (tmp_path / ".summary.json.tmp").symlink_to(outside)

    harness._write_same_or_new(target, b"safe\n")

    assert target.read_bytes() == b"safe\n"
    assert outside.read_text() == "unchanged"


def test_m23_and_m25_evidence_remain_unchanged(tmp_path: Path) -> None:
    harness = _load_harness()
    evaluation_root = _evaluation_root(tmp_path)
    before = harness.protected_evidence_hashes(evaluation_root)

    harness.run_evaluation(
        PROTOCOL,
        evaluation_root / "m26" / "runs" / "frozen-history",
        execution="controlled",
        evaluation_root=evaluation_root,
        repo_root=ROOT,
    )

    assert harness.protected_evidence_hashes(evaluation_root) == before
