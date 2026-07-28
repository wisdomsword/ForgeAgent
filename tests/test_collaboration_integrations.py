"""Entry-point contracts for M22 collaboration modes."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from rich.console import Console

import forgeagent.cli as cli_module
from forgeagent.cli import build_parser, repl, run_collaboration_once
from forgeagent.client import MockClient
from forgeagent.collaboration import (
    CollaborationReport,
    CollaborationRoleConfigurationError,
    CollaborationRunner,
    CollaborationUsage,
    headless_plan_confirmer,
)
from forgeagent.models import AssistantMessage, ModelCapability, TokenUsage
from forgeagent.task import Task
from forgeagent.tools import Tool, ToolOutcome, default_registry


def _report(**overrides: object) -> CollaborationReport:
    values: dict[str, object] = {
        "collaboration_id": "a" * 32,
        "mode": "duo",
        "status": "completed",
        "stop_reason": "completed",
        "phase": "completed",
        "plan_item_count": 1,
        "passed_item_count": 1,
        "failed_item_count": 0,
        "generator_attempts": 1,
        "evaluator_attempts": 1,
        "rejections": 0,
        "rounds": 2,
        "usage": CollaborationUsage(input_tokens=3, output_tokens=2),
        "usage_available": True,
        "evidence": (),
    }
    values.update(overrides)
    return CollaborationReport(**values)


def _reply(text: str) -> AssistantMessage:
    return AssistantMessage(
        content=text,
        usage=TokenUsage(input_tokens=1, output_tokens=1, total_prompt_tokens=1),
        stop_reason="end_turn",
    )


def _done() -> str:
    return "---\ntask_status:\n  completed: true\n  confidence: 0.9\n---\ndone"


def test_run_parser_accepts_collaboration_policy_flags():
    args = build_parser().parse_args(
        [
            "run",
            "implement parser.py",
            "--mode",
            "triad",
            "--planner-model",
            "planner",
            "--evaluator-model",
            "evaluator",
            "--max-rejections",
            "4",
        ]
    )

    assert args.mode == "triad"
    assert args.planner_model == "planner"
    assert args.evaluator_model == "evaluator"
    assert args.max_rejections == 4


def test_repl_collaboration_commands_share_help_and_completion_metadata():
    assert "/duo" in cli_module._SLASH_COMMAND_USAGE
    assert "/triad" in cli_module._SLASH_COMMAND_USAGE
    assert "cost" in cli_module._SLASH_COMMAND_USAGE["/duo"].lower()
    assert "planner" in cli_module._SLASH_COMMAND_USAGE["/triad"].lower()


def test_repl_missing_collaboration_goal_prints_usage_without_running(monkeypatch):
    calls: list[object] = []
    monkeypatch.setattr(cli_module, "run_collaboration_once", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: None)
    console = Console(record=True, force_terminal=False, file=__import__("io").StringIO())
    inputs = iter(["/duo", "/triad", "quit"])

    repl(
        tier="restricted",
        model="mock",
        client_factory=lambda _model: SimpleNamespace(),
        console=console,
        read_line=lambda _prompt: next(inputs),
        confirmation_available=False,
        no_identity=True,
        no_memory=True,
        use_registry_snapshot=False,
    )

    assert calls == []
    rendered = console.export_text()
    assert "usage: /duo <goal>" in rendered
    assert "usage: /triad <goal>" in rendered


def test_repl_duo_dispatches_only_the_goal(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: None)
    monkeypatch.setattr(
        cli_module,
        "run_collaboration_once",
        lambda goal, **kwargs: calls.append((goal, kwargs["mode"])) or _report(),
    )
    inputs = iter(["/duo verify the report", "quit"])

    repl(
        tier="restricted",
        model="mock",
        client_factory=lambda _model: SimpleNamespace(),
        read_line=lambda _prompt: next(inputs),
        confirmation_available=False,
        no_identity=True,
        no_memory=True,
        use_registry_snapshot=False,
    )

    assert calls == [("verify the report", "duo")]


def test_repl_programming_goal_uses_single(monkeypatch):
    single_calls: list[str] = []
    collaboration_calls: list[object] = []
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: None)
    monkeypatch.setattr(
        cli_module,
        "run_once",
        lambda goal, **kwargs: (
            single_calls.append(goal) or SimpleNamespace(status=SimpleNamespace(solved=True))
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "run_collaboration_once",
        lambda *args, **kwargs: collaboration_calls.append((args, kwargs)),
    )
    console = Console(record=True, force_terminal=False, file=__import__("io").StringIO())
    inputs = iter(["Add a unit test", "quit"])

    repl(
        tier="restricted",
        model="mock",
        client_factory=lambda _model: SimpleNamespace(),
        console=console,
        read_line=lambda _prompt: next(inputs),
        confirmation_available=False,
        no_identity=True,
        no_memory=True,
        use_registry_snapshot=False,
    )

    assert single_calls == ["Add a unit test"]
    assert collaboration_calls == []
    assert "programming task" not in console.export_text()


def test_repl_explicit_duo_does_not_read_override_confirmation(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: None)
    monkeypatch.setattr(
        cli_module,
        "run_collaboration_once",
        lambda goal, **kwargs: calls.append((goal, kwargs["mode"])) or _report(),
    )
    inputs = iter(["/duo Add a unit test", "quit"])

    repl(
        tier="restricted",
        model="mock",
        client_factory=lambda _model: SimpleNamespace(),
        read_line=lambda _prompt: next(inputs),
        confirmation_available=True,
        no_identity=True,
        no_memory=True,
        use_registry_snapshot=False,
    )

    assert calls == [("Add a unit test", "duo")]


def test_run_collaboration_wraps_role_client_configuration_errors(tmp_path, monkeypatch):
    capability = ModelCapability(
        model_id="mock",
        context_window=4096,
        max_output_tokens=512,
        supports_thinking=False,
        thinking_always_on=False,
        supports_effort=False,
        client_kind="anthropic",
    )

    class ProbeClient:
        def __init__(self) -> None:
            self.capability = capability

        def close(self) -> None:
            pass

    built = 0

    def factory(model: str):
        nonlocal built
        built += 1
        if model == "bad-evaluator":
            raise RuntimeError("private provider detail")
        return ProbeClient()

    class FakeRunner:
        @classmethod
        def create(cls, **kwargs):
            builder = kwargs["role_task_builder"]
            with pytest.raises(CollaborationRoleConfigurationError):
                builder("evaluator", 1, SimpleNamespace(), "prompt")
            return cls()

        def run(self, goal, *, cancel_event=None):
            return _report()

        def close(self):
            pass

    monkeypatch.setattr(cli_module, "CollaborationRunner", FakeRunner)

    with pytest.raises(CollaborationRoleConfigurationError):
        run_collaboration_once(
            "verify output",
            mode="duo",
            tier="trusted",
            model="generator",
            planner_model="planner",
            evaluator_model="bad-evaluator",
            max_rejections=2,
            client_factory=factory,
            allowed_root=str(tmp_path),
            console=Console(record=True, force_terminal=False),
        )
    assert built >= 1


def test_collaboration_renderer_omits_private_goal_and_absolute_path(monkeypatch, tmp_path):
    secret = "entry-secret-value"
    monkeypatch.setenv("ENTRY_SECRET", secret)
    report = _report(
        status="stopped",
        stop_reason="rejection_limit",
        phase="stopped",
        passed_item_count=0,
        failed_item_count=1,
        evidence=(f"failed at {tmp_path}/artifact.txt with {secret}",),
    )
    console = Console(record=True, force_terminal=False)

    cli_module._render_collaboration_report(report, console)

    rendered = console.export_text()
    assert "rejection_limit" in rendered
    assert secret not in rendered
    assert str(tmp_path) not in rendered


def test_loop_context_is_untrusted_role_data_and_checkpoint_only_extends_generator(tmp_path):
    plan = {
        "name": "SubmitPlan",
        "arguments": {
            "items": [
                {
                    "id": "artifact",
                    "behavior": "The requested artifact is present",
                    "acceptance": "A reader can observe the requested content",
                },
                {
                    "id": "quality",
                    "behavior": "The artifact is internally consistent",
                    "acceptance": "All observable statements agree",
                },
            ]
        },
    }
    evaluation = {
        "name": "SubmitEvaluation",
        "arguments": {
            "results": [
                {
                    "id": "artifact",
                    "passed": True,
                    "observed": "visible result",
                    "expected": "visible result",
                    "location": "artifact.txt",
                },
                {
                    "id": "quality",
                    "passed": True,
                    "observed": "consistent result",
                    "expected": "consistent result",
                    "location": "artifact.txt",
                },
            ]
        },
    }
    scripts = {
        "planner": [_reply(f"<!-- ToolCall: {json.dumps(plan)} -->")],
        "generator": [_reply('<!-- ToolCall: {"name":"SubmitCandidate","arguments":{}} -->')],
        "evaluator": [_reply(f"<!-- ToolCall: {json.dumps(evaluation)} -->")],
    }
    role_data: dict[str, dict[str, object]] = {}
    role_tools: dict[str, set[str]] = {}

    class RecordingClient(MockClient):
        def __init__(self, role: str):
            super().__init__(scripts[role])
            self.role = role

        def complete(self, messages, params=None):
            if self.role not in role_data:
                role_data[self.role] = json.loads(str(messages[-1].content))
            return super().complete(messages, params)

    def build_role(role, attempt, registry, system_prompt):
        del attempt
        role_tools[role] = set(registry.arg_schemas())
        return Task(RecordingClient(role), tool_registry=registry, system_prompt=system_prompt)

    class CheckpointArgs(BaseModel):
        pass

    class CheckpointTool(Tool):
        name = "Checkpoint"
        args_model = CheckpointArgs
        risk_level = "low"

        def run(self, args, ctx):
            del args, ctx
            return ToolOutcome(tool=self.name, success=True)

    extra_registry = default_registry()
    extra_registry.register(CheckpointTool())
    suffix = 'UNTRUSTED LOOP STATE\n{"handoff":"continue from durable item"}'
    runner = CollaborationRunner.create(
        mode="triad",
        goal="create artifact",
        allowed_root=str(tmp_path),
        role_task_builder=build_role,
        plan_confirmer=headless_plan_confirmer("preauthorize"),
        generator_registry=extra_registry,
        task_data_suffix=suffix,
    )

    report = runner.run("create artifact")
    runner.close()
    assert report.status == "completed"
    assert role_data["planner"]["loop_context"] == suffix
    assert role_data["generator"]["loop_context"] == suffix
    assert "loop_context" not in role_data["evaluator"]
    assert "Checkpoint" not in role_tools["planner"]
    assert "Checkpoint" in role_tools["generator"]
    assert "Checkpoint" not in role_tools["evaluator"]


def test_cli_programming_goal_uses_run_once(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: None)
    monkeypatch.setattr(cli_module, "resolve_cli_identity", lambda **kwargs: None)
    monkeypatch.setattr(cli_module, "_load_skill_registry", lambda **kwargs: None)
    monkeypatch.setattr(
        cli_module,
        "run_once",
        lambda goal, **kwargs: (
            calls.append(goal) or SimpleNamespace(status=SimpleNamespace(solved=True))
        ),
    )

    code = cli_module.main(
        ["--no-identity", "--no-memory", "run", "Add a unit test"],
        client_factory=lambda _model: SimpleNamespace(),
    )

    assert code == 0
    assert calls == ["Add a unit test"]


def test_cli_run_single_nonprogramming_uses_unchanged_run_once(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: None)
    monkeypatch.setattr(cli_module, "resolve_cli_identity", lambda **kwargs: None)
    monkeypatch.setattr(cli_module, "_load_skill_registry", lambda **kwargs: None)
    monkeypatch.setattr(
        cli_module,
        "run_once",
        lambda goal, **kwargs: (
            calls.append(goal) or SimpleNamespace(status=SimpleNamespace(solved=True))
        ),
    )

    code = cli_module.main(
        ["--no-identity", "--no-memory", "run", "Summarize this report"],
        client_factory=lambda _model: SimpleNamespace(),
    )

    assert code == 0
    assert calls == ["Summarize this report"]
