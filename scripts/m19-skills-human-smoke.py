#!/usr/bin/env python3
"""Key-free deterministic human smoke harness for the M19 Skills runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from forgeagent.client import ModelClient
from forgeagent.models import (
    AssistantMessage,
    GenerationParams,
    Message,
    ModelCapability,
    TokenUsage,
)
from forgeagent.skills import SkillRegistry

_SKILL_NAME = "review-python"
_USER_MARKER = "USER_SKILL"
_PROJECT_V1_MARKER = "PROJECT_SKILL_V1"
_PROJECT_V2_MARKER = "PROJECT_SKILL_V2"


@dataclass(frozen=True)
class SmokeFixture:
    home: Path
    project: Path
    user_skill: Path
    project_skill: Path


@dataclass
class SmokeState:
    observed_markers: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


def _skill_document(marker: str, trigger: str) -> str:
    return f"""---
name: {_SKILL_NAME}
trigger: {trigger}
---

## Steps

1. Inspect the deterministic marker `{marker}`.

## Failure branches

- If `{marker}` is missing, report the missing marker and stop.

## Completion criteria

- The feedback contains `{marker}`.
"""


def _write_skill(path: Path, marker: str, trigger: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_skill_document(marker, trigger), encoding="utf-8")


def create_fixture(root: Path) -> SmokeFixture:
    home = root / "home"
    project = root / "project"
    user_skill = home / ".forgeagent" / "skills" / _SKILL_NAME / "SKILL.md"
    project_skill = project / ".forgeagent" / "skills" / _SKILL_NAME / "SKILL.md"
    _write_skill(user_skill, _USER_MARKER, "Use the user review procedure.")
    _write_skill(project_skill, _PROJECT_V1_MARKER, "Use the project review procedure.")
    return SmokeFixture(
        home=home,
        project=project,
        user_skill=user_skill,
        project_skill=project_skill,
    )


def _reply(content: str) -> AssistantMessage:
    return AssistantMessage(content=content, usage=TokenUsage(), stop_reason="end_turn")


def _skill_call() -> str:
    payload = {"name": "Skill", "arguments": {"name": _SKILL_NAME}}
    return f"<!-- ToolCall: {json.dumps(payload)} -->"


def _done(detail: str) -> str:
    return f"---\ntask_status:\n  completed: true\n  confidence: 1.0\n---\n{detail}"


def _failed(detail: str) -> str:
    return f"---\ntask_status:\n  completed: false\n  status: failed\n---\n{detail}"


class DeterministicSkillClient(ModelClient):
    def __init__(self, expected_marker: str, state: SmokeState) -> None:
        self.expected_marker = expected_marker
        self._state = state
        self._round = 0
        self._capability = ModelCapability(
            model_id="mock",
            context_window=100_000,
            max_output_tokens=4_096,
            supports_thinking=False,
            thinking_always_on=False,
            supports_effort=False,
            client_kind="anthropic",
        )

    def complete(
        self,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> AssistantMessage:
        del params
        self._round += 1
        if self._round == 1:
            return _reply(_skill_call())
        visible = "\n".join(item.content for item in messages if isinstance(item.content, str))
        if self.expected_marker in visible:
            self._state.observed_markers.append(self.expected_marker)
            return _reply(_done(f"PASS progressive loading: {self.expected_marker}"))
        failure = f"missing feedback marker: {self.expected_marker}"
        self._state.failures.append(failure)
        return _reply(_failed(f"FAIL {failure}"))

    @property
    def capability(self) -> ModelCapability:
        return self._capability


class SmokeClientFactory:
    def __init__(self, fixture: SmokeFixture, state: SmokeState) -> None:
        self._fixture = fixture
        self._state = state
        self._task_count = 0

    def __call__(self, _model: str) -> ModelClient:
        task_index = self._task_count
        self._task_count += 1
        if task_index == 0:
            _write_skill(
                self._fixture.project_skill,
                _PROJECT_V2_MARKER,
                "Use the reloaded project review procedure.",
            )
        marker = _PROJECT_V1_MARKER if task_index == 0 else _PROJECT_V2_MARKER
        return DeterministicSkillClient(marker, self._state)


def evaluate_checks(
    state: SmokeState,
    *,
    trust_matches: bool,
    completion_ok: bool,
    history_ok: bool,
) -> dict[str, bool]:
    observed = state.observed_markers
    return {
        "progressive V1": len(observed) >= 1 and observed[0] == _PROJECT_V1_MARKER,
        "reload V2": len(observed) >= 2 and observed[1] == _PROJECT_V2_MARKER,
        "two-round Skill tasks": observed[:2] == [_PROJECT_V1_MARKER, _PROJECT_V2_MARKER]
        and not state.failures,
        "Skill trust V2": trust_matches,
        "slash completion": completion_ok,
        "arrow history": history_ok,
    }


def trust_record_matches_v2(fixture: SmokeFixture) -> bool:
    registry = SkillRegistry.load(
        home=str(fixture.home),
        allowed_root=str(fixture.project),
        confirmer=None,
    )
    rendered = registry.read(_SKILL_NAME)
    return rendered is not None and _PROJECT_V2_MARKER in rendered
