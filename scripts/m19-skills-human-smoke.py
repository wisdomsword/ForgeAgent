#!/usr/bin/env python3
"""Key-free deterministic human smoke harness for the M19 Skills runtime."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

import forgeagent.cli as cli_module
import forgeagent.context as context_module
import forgeagent.mcp_manager as mcp_manager_module
import forgeagent.model_registry as model_registry_module
from forgeagent.client import ModelClient
from forgeagent.models import (
    AssistantMessage,
    GenerationParams,
    Message,
    ModelCapability,
    TokenUsage,
)
from forgeagent.secret_policy import is_secret_name
from forgeagent.skills import SkillRegistry

_SKILL_NAME = "review-python"
_USER_MARKER = "USER_SKILL"
_PROJECT_V1_MARKER = "PROJECT_SKILL_V1"
_PROJECT_V2_MARKER = "PROJECT_SKILL_V2"
repl = cli_module.repl


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
    cancelled: bool = False


def _skill_document(marker: str, trigger: str) -> str:
    return f"""---
name: {_SKILL_NAME}
trigger: {trigger}
---

## Steps

1. Inspect the deterministic marker `{marker}`.

## Failure Branches

- If `{marker}` is missing, report the missing marker and stop.

## Completion Criteria

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
        marker = (
            _PROJECT_V2_MARKER if trust_record_matches_v2(self._fixture) else _PROJECT_V1_MARKER
        )
        return DeterministicSkillClient(marker, self._state)


def evaluate_checks(
    state: SmokeState,
    *,
    trust_matches: bool,
    completion_ok: bool,
    history_ok: bool,
) -> dict[str, bool]:
    observed = state.observed_markers
    progressive_v1 = observed[:1] == [_PROJECT_V1_MARKER]
    reload_v2 = progressive_v1 and _PROJECT_V2_MARKER in observed[1:]
    return {
        "progressive V1": progressive_v1,
        "reload V2": reload_v2,
        "two-round Skill tasks": reload_v2 and not state.failures,
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


@contextmanager
def temporary_smoke_environment(root: Path) -> Iterator[SmokeFixture]:
    fixture = create_fixture(root)
    original_home = os.environ.get("HOME")
    original_cwd = Path.cwd()
    original_secret_environment = {
        name: value for name, value in os.environ.items() if is_secret_name(name)
    }
    original_config_paths = (
        context_module._DEFAULT_CONFIG_PATH,
        mcp_manager_module.DEFAULT_USER_MCP_PATH,
        model_registry_module.DEFAULT_USER_MODELS_PATH,
        model_registry_module.DEFAULT_USER_CONFIG_PATH,
    )
    config_root = fixture.home / ".forgeagent"
    try:
        for name in original_secret_environment:
            os.environ.pop(name, None)
        os.environ["HOME"] = str(fixture.home)
        os.chdir(fixture.project)
        context_module._DEFAULT_CONFIG_PATH = config_root / "config.yaml"
        mcp_manager_module.DEFAULT_USER_MCP_PATH = config_root / "mcp.yaml"
        model_registry_module.DEFAULT_USER_MODELS_PATH = config_root / "models.yaml"
        model_registry_module.DEFAULT_USER_CONFIG_PATH = config_root / "config.yaml"
        yield fixture
    finally:
        (
            context_module._DEFAULT_CONFIG_PATH,
            mcp_manager_module.DEFAULT_USER_MCP_PATH,
            model_registry_module.DEFAULT_USER_MODELS_PATH,
            model_registry_module.DEFAULT_USER_CONFIG_PATH,
        ) = original_config_paths
        try:
            os.chdir(original_cwd)
        finally:
            for name in list(os.environ):
                if is_secret_name(name):
                    os.environ.pop(name, None)
            os.environ.update(original_secret_environment)
            if original_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = original_home


def _track_cancellation(reader: Callable[[str], str], state: SmokeState) -> Callable[[str], str]:
    def tracked_reader(prompt: str) -> str:
        try:
            return reader(prompt)
        except KeyboardInterrupt:
            state.cancelled = True
            raise

    return tracked_reader


def _print_instructions() -> None:
    print(
        """
M19 deterministic human smoke

1. Approve the initial project Skill with: y
2. At one forge> prompt type '/', then 'm'. Keep the leading '/' visible. Backspace to '/',
   type 're', and observe the candidates changing. Do not press Enter on /m or /re.
   Use Ctrl-U to clear the line; if you accidentally submit m or re, continue anyway.
3. Run /help. At the next prompt press Up, then Down.
4. Run: review first snapshot
5. Run: /reload, then approve the changed project Skill with: y
6. Run: review reloaded snapshot
7. Run: quit
""".strip()
    )


def _ask_yes(question: str) -> bool:
    try:
        answer = input(f"{question} [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def _print_summary(checks: dict[str, bool], failures: list[str]) -> int:
    print("\nM19 human smoke results")
    for name, passed in checks.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
    for failure in failures:
        print(f"  detail: {failure}")
    passed = all(checks.values())
    print(f"M19 HUMAN SMOKE: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


def main() -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("M19 human smoke requires a real interactive terminal.", file=sys.stderr)
        return 2
    state = SmokeState()
    try:
        with TemporaryDirectory(prefix="forgeagent-m19-human-") as raw_root:
            with temporary_smoke_environment(Path(raw_root)) as fixture:
                _print_instructions()
                read_line = _track_cancellation(cli_module._make_interactive_reader(), state)
                repl(
                    tier="restricted",
                    model="mock",
                    client_factory=SmokeClientFactory(fixture, state),
                    use_registry_snapshot=False,
                    read_line=read_line,
                )
                if state.cancelled:
                    print("\nM19 human smoke CANCELLED", file=sys.stderr)
                    return 130
                completion_ok = _ask_yes("Did slash candidates filter while typing?")
                history_ok = _ask_yes("Did Up/Down replay and restore input history?")
                checks = evaluate_checks(
                    state,
                    trust_matches=trust_record_matches_v2(fixture),
                    completion_ok=completion_ok,
                    history_ok=history_ok,
                )
                return _print_summary(checks, state.failures)
    except KeyboardInterrupt:
        print("\nM19 human smoke CANCELLED", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
