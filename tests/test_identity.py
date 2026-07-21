"""Tests for runtime identity prompt composition."""

from __future__ import annotations

import itertools
import json
import os
from pathlib import Path

import pytest

import forgeagent.identity as identity_module
from forgeagent.identity import ApprovedIdentity, compose_system_prompt


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def _labelled_combinations() -> list[tuple[str | None, str | None, str | None, str | None]]:
    markers = {
        "soul": "SOUL-MARKER",
        "user": "USER-MARKER",
        "project_agents": "AGENTS-MARKER",
        "memory": "MEMORY-MARKER",
    }
    return [
        tuple(
            markers[name] if present else None for name, present in zip(markers, flags, strict=True)
        )
        for flags in itertools.product([False, True], repeat=4)
    ]


@pytest.mark.parametrize("soul,user,project_agents,memory", _labelled_combinations())
def test_compose_system_prompt_combination_matrix(soul, user, project_agents, memory):
    identity = ApprovedIdentity(
        soul=soul,
        user=user,
        project_agents=project_agents,
        memory=memory,
    )
    rendered = compose_system_prompt(identity)

    assert "This conversation is driven by ForgeAgent" in rendered
    if soul is not None:
        assert soul in rendered
        assert "No custom Agent Identity (SOUL)" not in rendered
    else:
        assert "No custom Agent Identity (SOUL)" in rendered
    for value, heading in (
        (user, "## User Context"),
        (project_agents, "## Approved Project Instructions"),
        (memory, "## Project Memory"),
    ):
        if value is not None:
            assert heading in rendered
            assert value in rendered
        else:
            assert heading not in rendered


def test_compose_system_prompt_section_order():
    identity = ApprovedIdentity(
        soul="SOUL-MARKER",
        user="USER-MARKER",
        project_agents="AGENTS-MARKER",
        memory="MEMORY-MARKER",
    )
    rendered = compose_system_prompt(identity)
    assert (
        rendered.index("SOUL-MARKER")
        < rendered.index("This conversation is driven by ForgeAgent")
        < rendered.index("USER-MARKER")
        < rendered.index("AGENTS-MARKER")
        < rendered.index("MEMORY-MARKER")
    )


def test_compose_system_prompt_protocol_is_fixed_text():
    baseline = compose_system_prompt(ApprovedIdentity(None, None, None, None))
    with_identity = compose_system_prompt(ApprovedIdentity("X", "Y", "Z", "W"))
    assert baseline.count("Exec") == with_identity.count("Exec")


def test_resolve_identity_file_validates_missing_regular_and_escaping_paths(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    identity_dir = root / ".forgeagent"
    root.mkdir()
    outside.mkdir()
    identity_dir.mkdir()
    (identity_dir / "REAL.md").write_text("content", encoding="utf-8")

    assert (
        identity_module._resolve_identity_file(
            str(identity_dir), "REAL.md", containment_root=str(root)
        )
        is not None
    )
    assert (
        identity_module._resolve_identity_file(
            str(identity_dir), "MISSING.md", containment_root=str(root)
        )
        is None
    )

    outside_file = outside / "SECRET.md"
    outside_file.write_text("leaked", encoding="utf-8")
    os.symlink(outside_file, identity_dir / "ESCAPE.md")
    with pytest.raises(identity_module._IdentityPathError):
        identity_module._resolve_identity_file(
            str(identity_dir), "ESCAPE.md", containment_root=str(root)
        )

    (identity_dir / "ADIR.md").mkdir()
    with pytest.raises(identity_module._IdentityPathError):
        identity_module._resolve_identity_file(
            str(identity_dir), "ADIR.md", containment_root=str(root)
        )


def test_resolve_identity_file_rejects_identity_directory_symlink_escape(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "AGENTS.md").write_text("outside", encoding="utf-8")
    os.symlink(outside, root / ".forgeagent")

    with pytest.raises(identity_module._IdentityPathError):
        identity_module._resolve_identity_file(
            str(root / ".forgeagent"), "AGENTS.md", containment_root=str(root)
        )


def test_identity_digests_are_deterministic_unambiguous_and_domain_separated(tmp_path):
    raw = identity_module._raw_content_digest(b"agents content", b"memory content")
    assert raw == identity_module._raw_content_digest(b"agents content", b"memory content")
    assert identity_module._raw_content_digest(
        b"agents content", None
    ) != identity_module._raw_content_digest(None, b"agents content")
    assert identity_module._raw_content_digest(b"AB", b"CD") != identity_module._raw_content_digest(
        b"A", b"BCD"
    )

    effective = identity_module._effective_input_digest("agents content", "memory content")
    assert effective == identity_module._effective_input_digest("agents content", "memory content")
    assert effective != raw

    project_id = identity_module.canonical_project_id_digest(str(tmp_path))
    assert len(project_id) == 64
    assert str(tmp_path) not in project_id


def test_load_identity_all_files_missing(tmp_path):
    home = tmp_path / "home"
    root = tmp_path / "root"
    home.mkdir()
    root.mkdir()
    snapshot = identity_module.load_identity(str(home), str(root))
    assert snapshot.soul is None
    assert snapshot.user is None
    assert snapshot.agents is None
    assert snapshot.memory is None


def test_load_identity_partial_presence(tmp_path):
    home = tmp_path / "home"
    root = tmp_path / "root"
    home.mkdir()
    root.mkdir()
    _write(str(home / ".forgeagent" / "USER.md"), "prefers terse answers")
    snapshot = identity_module.load_identity(str(home), str(root))
    assert snapshot.user == "prefers terse answers"
    assert snapshot.soul is None
    assert snapshot.agents is None
    assert snapshot.memory is None


def test_load_identity_project_root_independent_of_cwd(tmp_path, monkeypatch):
    home = tmp_path / "home"
    root = tmp_path / "root"
    elsewhere = tmp_path / "elsewhere"
    home.mkdir()
    root.mkdir()
    elsewhere.mkdir()
    _write(str(root / ".forgeagent" / "AGENTS.md"), "root rule")
    monkeypatch.chdir(str(elsewhere))
    snapshot = identity_module.load_identity(str(home), str(root))
    assert snapshot.agents == "root rule"


def test_load_identity_rejects_symlink_escape_and_reports_diagnostic(tmp_path):
    home = tmp_path / "home"
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    home.mkdir()
    root.mkdir()
    outside.mkdir()
    _write(str(outside / "SECRET.md"), "leaked project secret")
    (root / ".forgeagent").mkdir()
    os.symlink(str(outside / "SECRET.md"), str(root / ".forgeagent" / "AGENTS.md"))
    diagnostics = []
    snapshot = identity_module.load_identity(str(home), str(root), diagnostic=diagnostics.append)
    assert snapshot.agents is None
    assert snapshot.memory is None
    assert diagnostics == ["project identity snapshot rejected: _IdentityPathError"]


def test_load_identity_masks_secret_values(tmp_path, monkeypatch):
    home = tmp_path / "home"
    root = tmp_path / "root"
    home.mkdir()
    root.mkdir()
    monkeypatch.setenv("FORGEAGENT_TEST_TOKEN", "leaked-value-1234567890")
    _write(str(root / ".forgeagent" / "AGENTS.md"), "the token is leaked-value-1234567890")
    snapshot = identity_module.load_identity(str(home), str(root))
    assert "leaked-value-1234567890" not in snapshot.agents
    assert "REDACTED" in snapshot.agents


def test_load_identity_soul_over_limit_raises(tmp_path):
    home = tmp_path / "home"
    root = tmp_path / "root"
    home.mkdir()
    root.mkdir()
    _write(str(home / ".forgeagent" / "SOUL.md"), "x" * (33 * 1024))
    with pytest.raises(identity_module.IdentityConfigError):
        identity_module.load_identity(str(home), str(root))


def test_load_identity_agents_over_limit_strips_with_diagnostic(tmp_path):
    home = tmp_path / "home"
    root = tmp_path / "root"
    home.mkdir()
    root.mkdir()
    _write(str(root / ".forgeagent" / "AGENTS.md"), "x" * (33 * 1024))
    diagnostics = []
    snapshot = identity_module.load_identity(str(home), str(root), diagnostic=diagnostics.append)
    assert snapshot.agents is None
    assert diagnostics and diagnostics[0].startswith("AGENTS.md stripped:")


def test_load_identity_never_truncates(tmp_path):
    home = tmp_path / "home"
    root = tmp_path / "root"
    home.mkdir()
    root.mkdir()
    content = "y" * (10 * 1024)
    _write(str(home / ".forgeagent" / "USER.md"), content)
    snapshot = identity_module.load_identity(str(home), str(root))
    assert snapshot.user == content


def test_load_identity_home_resolved_at_call_time_after_import(tmp_path, monkeypatch):
    home = tmp_path / "home"
    root = tmp_path / "root"
    home.mkdir()
    root.mkdir()
    _write(str(home / ".forgeagent" / "SOUL.md"), "runtime home soul")
    monkeypatch.setenv("HOME", str(home))
    snapshot = identity_module.load_identity(allowed_root=str(root))
    assert snapshot.soul == "runtime home soul"


def test_load_identity_unreadable_file_raises_config_error_not_absence(tmp_path, monkeypatch):
    home = tmp_path / "home"
    root = tmp_path / "root"
    home.mkdir()
    root.mkdir()
    soul_path = home / ".forgeagent" / "SOUL.md"
    _write(str(soul_path), "unreadable content")
    original_read_bytes = Path.read_bytes

    def fail_selected_path(path):
        if path == soul_path.resolve():
            raise PermissionError("simulated unreadable SOUL")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_selected_path)
    with pytest.raises(identity_module.IdentityConfigError):
        identity_module.load_identity(str(home), str(root))


def test_load_identity_unreadable_project_file_raises_config_error(tmp_path, monkeypatch):
    home = tmp_path / "home"
    root = tmp_path / "root"
    home.mkdir()
    root.mkdir()
    agents_path = root / ".forgeagent" / "AGENTS.md"
    _write(str(agents_path), "unreadable project rule")
    original_read_bytes = Path.read_bytes

    def fail_selected_path(path):
        if path == agents_path.resolve():
            raise PermissionError("simulated unreadable AGENTS")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_selected_path)
    with pytest.raises(identity_module.IdentityConfigError):
        identity_module.load_identity(str(home), str(root))


def test_unreadable_identity_error_redacts_oserror_detail(tmp_path, monkeypatch):
    home = tmp_path / "home"
    root = tmp_path / "root"
    home.mkdir()
    root.mkdir()
    soul_path = home / ".forgeagent" / "SOUL.md"
    _write(str(soul_path), "unreadable content")
    original_read_bytes = Path.read_bytes
    leaked_path = f"{tmp_path}/private-secret-token"

    def fail_selected_path(path):
        if path == soul_path.resolve():
            raise PermissionError(f"denied {leaked_path}\n\x1b[31msecret")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_selected_path)
    with pytest.raises(identity_module.IdentityConfigError) as raised:
        identity_module.load_identity(str(home), str(root))
    message = str(raised.value)
    assert message == "SOUL.md exists but could not be read (PermissionError)"
    assert leaked_path not in message
    assert "\n" not in message
    assert "\x1b" not in message
    assert raised.value.__cause__ is None


def test_identity_diagnostic_escapes_control_characters(tmp_path):
    diagnostics = []
    identity_module._emit_identity_diagnostic(diagnostics.append, "diagnostic\nline\twith\x1b[31m")
    assert diagnostics == [r"diagnostic\x0aline\x09with\x1b[31m"]


def test_user_identity_path_error_does_not_retain_oserror_cause_chain(tmp_path, monkeypatch):
    home = tmp_path / "home"
    root = tmp_path / "root"
    home.mkdir()
    root.mkdir()
    soul_path = home / ".forgeagent" / "SOUL.md"
    _write(str(soul_path), "identity")
    original_lstat = identity_module.os.lstat
    leaked_path = f"{tmp_path}/identity-secret-path"

    def fail_selected_path(path):
        if os.fspath(path) == str(soul_path):
            raise PermissionError(f"denied {leaked_path}\n\x1b[31msecret")
        return original_lstat(path)

    monkeypatch.setattr(identity_module.os, "lstat", fail_selected_path)
    with pytest.raises(identity_module.IdentityConfigError) as raised:
        identity_module.load_identity(str(home), str(root))

    error = raised.value
    causes = []
    current = error
    while current is not None:
        causes.append(current)
        current = current.__cause__
    contexts = []
    current = error
    while current is not None:
        contexts.append(current)
        current = current.__context__
    assert error.__cause__ is None
    assert all(leaked_path not in str(cause) for cause in causes)
    assert all("\n" not in str(cause) and "\x1b" not in str(cause) for cause in causes)
    assert all(not isinstance(context, OSError) for context in contexts)
    assert all(leaked_path not in str(context) for context in contexts)


def test_load_identity_rejects_masked_user_total_over_limit(tmp_path, monkeypatch):
    home = tmp_path / "home"
    root = tmp_path / "root"
    home.mkdir()
    root.mkdir()
    secret = "secret89"
    monkeypatch.setenv("FORGEAGENT_TEST_TOKEN", secret)
    repeated = secret * ((32 * 1024) // len(secret))
    _write(str(home / ".forgeagent" / "SOUL.md"), repeated)
    _write(str(home / ".forgeagent" / "USER.md"), repeated)

    masked_repeated = identity_module._mask(repeated)
    assert 2 * len(masked_repeated.encode("utf-8")) > identity_module._MAX_EFFECTIVE_TOTAL_BYTES

    with pytest.raises(identity_module.IdentityConfigError, match="combined masked"):
        identity_module.load_identity(str(home), str(root))


def test_load_identity_strips_largest_project_file_for_masked_total_without_truncation(
    tmp_path,
):
    home = tmp_path / "home"
    root = tmp_path / "root"
    home.mkdir()
    root.mkdir()
    soul = "s" * (32 * 1024)
    user = "u" * (32 * 1024)
    agents = "a" * 30_000
    memory = "m" * (32 * 1024)
    _write(str(home / ".forgeagent" / "SOUL.md"), soul)
    _write(str(home / ".forgeagent" / "USER.md"), user)
    _write(str(root / ".forgeagent" / "AGENTS.md"), agents)
    _write(str(root / ".forgeagent" / "MEMORY.md"), memory)
    diagnostics = []

    snapshot = identity_module.load_identity(str(home), str(root), diagnostic=diagnostics.append)

    assert snapshot.agents == agents
    assert snapshot.memory is None
    assert any(message.startswith("MEMORY.md stripped:") for message in diagnostics)
    assert all("truncat" not in message.lower() for message in diagnostics)


def _project_snapshot(**overrides):
    values = {
        "soul": "S",
        "user": "U",
        "agents": "AGENTS BODY",
        "memory": "MEMORY BODY",
        "raw_content_digest": "raw-1",
        "effective_input_digest": "eff-1",
    }
    values.update(overrides)
    return identity_module.IdentitySnapshot(**values)


def test_trust_record_primitives_validate_and_atomically_merge(tmp_path):
    path = str(tmp_path / "identity-trust.json")
    assert identity_module._load_trust_record(path) is None
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("{bad")
    with pytest.raises(identity_module._UnusableTrustRecordError):
        identity_module._load_trust_record(path)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"version": 2, "projects": {}}, handle)
    with pytest.raises(identity_module._UnusableTrustRecordError):
        identity_module._load_trust_record(path)
    os.unlink(path)
    assert identity_module._record_approval(path, "project-a", "raw-a", "eff-a")
    assert identity_module._record_approval(path, "project-b", "raw-b", "eff-b")
    record = identity_module._load_trust_record(path)
    assert set(record["projects"]) == {"project-a", "project-b"}


def test_trust_record_rejects_invalid_encoding_and_unknown_schema_fields(tmp_path):
    path = str(tmp_path / "identity-trust.json")
    with open(path, "wb") as handle:
        handle.write(b"\xff")
    with pytest.raises(identity_module._UnusableTrustRecordError):
        identity_module._load_trust_record(path)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"version": 1, "projects": {}, "extra": True}, handle)
    with pytest.raises(identity_module._UnusableTrustRecordError):
        identity_module._load_trust_record(path)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"version": True, "projects": {}}, handle)
    with pytest.raises(identity_module._UnusableTrustRecordError):
        identity_module._load_trust_record(path)


def test_trust_confirmation_summary_masks_controls_and_is_bounded():
    label = identity_module._project_label("/Users/someone/Code/ForgeAgent")
    assert "someone" not in label
    assert "ForgeAgent" in label
    summary = identity_module._trust_request_summary("agents\x1b[31m", "memory\rvalue")
    assert summary.index("AGENTS.md") < summary.index("MEMORY.md")
    assert "\x1b" not in summary and "\r" not in summary
    assert r"\x1b" in summary and r"\x0d" in summary
    bounded = identity_module._trust_request_summary("a" * 10000, "m" * 10000)
    assert len(bounded) < 5000
    assert "preview truncated" in bounded


def test_resolve_project_trust_decision_table(tmp_path):
    home = str(tmp_path / "home")
    root = str(tmp_path / "root")
    os.makedirs(home)
    os.makedirs(root)
    snapshot = _project_snapshot()
    assert identity_module.resolve_project_trust(snapshot, root, home, None).project_agents is None
    assert (
        identity_module.resolve_project_trust(snapshot, root, home, lambda request: False).memory
        is None
    )
    requests = []
    approved = identity_module.resolve_project_trust(
        snapshot, root, home, lambda request: requests.append(request) or True
    )
    assert approved.project_agents == snapshot.agents and len(requests) == 1
    calls = []
    reused = identity_module.resolve_project_trust(
        snapshot, root, home, lambda request: calls.append(request) or True
    )
    assert reused.memory == snapshot.memory and calls == []
    changed = _project_snapshot(
        agents="NEW", raw_content_digest="raw-2", effective_input_digest="eff-2"
    )
    identity_module.resolve_project_trust(
        changed, root, home, lambda request: calls.append(request) or True
    )
    assert len(calls) == 1


def test_malformed_trust_record_is_never_overwritten(tmp_path):
    home = str(tmp_path / "home")
    root = str(tmp_path / "root")
    os.makedirs(home)
    os.makedirs(root)
    path = os.path.join(home, ".forgeagent", "identity-trust.json")
    os.makedirs(os.path.dirname(path))
    original = "{corrupted"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(original)
    snapshot = _project_snapshot(soul=None, user=None, memory=None)
    assert (
        identity_module.resolve_project_trust(
            snapshot, root, home, lambda request: True, trust_record_path=path
        ).project_agents
        == "AGENTS BODY"
    )
    assert open(path, encoding="utf-8").read() == original
    calls = []
    identity_module.resolve_project_trust(
        snapshot, root, home, lambda request: calls.append(request) or True, trust_record_path=path
    )
    assert len(calls) == 1


def test_trust_persistence_failure_is_memory_only(tmp_path, monkeypatch):
    home = str(tmp_path / "home")
    root = str(tmp_path / "root")
    os.makedirs(home)
    os.makedirs(root)
    snapshot = _project_snapshot(soul=None, user=None, memory=None)
    diagnostics = []
    monkeypatch.setattr(
        identity_module,
        "_atomic_write_trust_record",
        lambda path, record: (_ for _ in ()).throw(PermissionError("no")),
    )
    approved = identity_module.resolve_project_trust(
        snapshot, root, home, lambda request: True, diagnostic=diagnostics.append
    )
    assert approved.project_agents == "AGENTS BODY"
    assert diagnostics == ["identity trust approval is memory-only: persistence failed"]
