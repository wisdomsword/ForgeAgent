"""Independent mock-replay harness for the G381-G400 identity candidates.

This module does NOT claim that a MockClient's scripted reply constitutes
evidence of real-model instruction-following. It only proves that SOUL/AGENTS
content mechanically reaches the composed system prompt that would be sent to
any client. The candidate table's prose descriptions are not themselves
executable verification; this file is.
"""

from __future__ import annotations

from pathlib import Path

from forgeagent.client import MockClient
from forgeagent.identity import ApprovedIdentity, load_identity, resolve_project_trust
from forgeagent.models import AssistantMessage, Role, TokenUsage
from forgeagent.task import Task


def _done() -> str:
    return "---\ntask_status:\n  completed: true\n  confidence: 0.9\n---\ndone"


def _reply(text: str, stop_reason: str = "end_turn") -> AssistantMessage:
    return AssistantMessage(content=text, usage=TokenUsage(), stop_reason=stop_reason)


class _RecordingTaskClient(MockClient):
    def __init__(self, script: list[AssistantMessage]):
        super().__init__(script=script)
        self.first_messages = None

    def complete(self, messages, params=None):
        if self.first_messages is None:
            self.first_messages = list(messages)
        return super().complete(messages, params)


def _run_with_identity(identity: ApprovedIdentity) -> str:
    client = _RecordingTaskClient(script=[_reply(_done())])
    task = Task(client, identity=identity)
    task.run("golden candidate mock replay")
    assert client.first_messages is not None
    system_msg = next(message for message in client.first_messages if message.role == Role.SYSTEM)
    return system_msg.content


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run_from_files(tmp_path: Path, *, soul: str | None = None, agents: str | None = None) -> str:
    home = tmp_path / "home"
    root = tmp_path / "root"
    home.mkdir()
    root.mkdir()
    if soul is not None:
        _write(home / ".forgeagent" / "SOUL.md", soul)
    if agents is not None:
        _write(root / ".forgeagent" / "AGENTS.md", agents)
    snapshot = load_identity(str(home), str(root))
    approved = resolve_project_trust(
        snapshot,
        str(root),
        str(home),
        (lambda request: True) if agents is not None else None,
    )
    return _run_with_identity(approved)


def test_g381_custom_soul_reaches_composed_system_prompt(tmp_path):
    """G381: 用户级 SOUL.md 完整出现在 Agent Identity 段。"""
    soul_text = "I am GOLDEN-CANDIDATE-SOUL, a mock identity for G381."
    rendered = _run_from_files(tmp_path, soul=soul_text)
    assert soul_text in rendered
    assert "No custom Agent Identity (SOUL)" not in rendered


def test_g383_approved_project_agents_reaches_composed_system_prompt(tmp_path):
    """G383: 已确认的项目级 AGENTS.md 完整出现在 Approved Project Instructions 段。"""
    agents_text = "GOLDEN-CANDIDATE-AGENTS-RULE: always cite file paths."
    rendered = _run_from_files(tmp_path, agents=agents_text)
    assert agents_text in rendered
    assert "Approved Project Instructions" in rendered


def test_g385_missing_identity_files_omit_their_sections():
    """G385: AGENTS/MEMORY 缺失时对应 section 标题不出现。"""
    rendered = _run_with_identity(
        ApprovedIdentity(soul=None, user=None, project_agents=None, memory=None)
    )
    assert "Approved Project Instructions" not in rendered
    assert "## Project Memory" not in rendered


def test_candidate_id_pattern_covers_g381_to_g400_without_g401():
    """The candidate parser accepts the expanded range and rejects adjacent IDs."""
    from tests.golden.runner import _CANDIDATE_ID

    for number in range(381, 401):
        assert _CANDIDATE_ID.fullmatch(f"G{number}")
    assert not _CANDIDATE_ID.fullmatch("G401")
