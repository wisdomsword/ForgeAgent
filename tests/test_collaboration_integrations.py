"""Entry-point contracts for M22 collaboration modes."""

from __future__ import annotations

import json
import stat
from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from rich.console import Console

import forgeagent.cli as cli_module
from forgeagent.audit import AuditEvent
from forgeagent.cli import build_parser, repl, run_collaboration_once
from forgeagent.client import MockClient
from forgeagent.collaboration import (
    CollaborationReport,
    CollaborationRoleConfigurationError,
    CollaborationRunner,
    CollaborationUsage,
    headless_plan_confirmer,
)
from forgeagent.execution_evidence import (
    ExecutionEvidence,
    ProgramArtifactStore,
    ToolExecutionRecord,
    resolve_local_artifact_path,
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
    assert "/single" in cli_module._SLASH_COMMAND_USAGE
    assert "/duo" in cli_module._SLASH_COMMAND_USAGE
    assert "/triad" in cli_module._SLASH_COMMAND_USAGE
    assert "cost" in cli_module._SLASH_COMMAND_USAGE["/duo"].lower()
    assert "planner" in cli_module._SLASH_COMMAND_USAGE["/triad"].lower()


class _AuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> bool:
        self.events.append(event)
        return True


def test_repl_single_command_emits_explicit_route_once_without_goal_data(monkeypatch):
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: None)
    monkeypatch.setattr(
        cli_module,
        "run_once",
        lambda _goal, **_kwargs: SimpleNamespace(status=SimpleNamespace(solved=True)),
    )
    sink = _AuditSink()
    inputs = iter(["/single PRIVATE_GOAL", "quit"])

    repl(
        tier="restricted",
        model="mock",
        client_factory=lambda _model: SimpleNamespace(),
        read_line=lambda _prompt: next(inputs),
        confirmation_available=False,
        no_identity=True,
        no_memory=True,
        use_registry_snapshot=False,
        audit_sink=sink,
    )

    routes = [event for event in sink.events if event.event_type == "collaboration.route"]
    assert len(routes) == 1
    assert routes[0].parameters == {
        "mode": "single",
        "reason": "explicit",
        "requested_mode": "single",
        "override_required": False,
    }
    assert "PRIVATE_GOAL" not in routes[0].model_dump_json()


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


@pytest.mark.parametrize("mode", ["duo", "triad"])
def test_run_collaboration_emits_route_once_without_private_data(tmp_path, monkeypatch, mode):
    class ProbeClient:
        def close(self) -> None:
            pass

    class FakeRunner:
        @classmethod
        def create(cls, **_kwargs):
            return cls()

        def run(self, _goal, *, cancel_event=None):
            del cancel_event
            return _report(mode=mode)

        def close(self):
            pass

    monkeypatch.setattr(cli_module, "CollaborationRunner", FakeRunner)
    monkeypatch.setattr(cli_module, "_validate_client_context_policy", lambda *_args: None)
    sink = _AuditSink()

    run_collaboration_once(
        "PRIVATE_GOAL",
        mode=mode,
        tier="trusted",
        model="mock",
        planner_model=None,
        evaluator_model=None,
        max_rejections=2,
        client_factory=lambda _model: ProbeClient(),
        allowed_root=str(tmp_path),
        console=Console(record=True, force_terminal=False),
        audit_sink=sink,
    )

    routes = [event for event in sink.events if event.event_type == "collaboration.route"]
    assert len(routes) == 1
    assert routes[0].parameters == {
        "mode": mode,
        "reason": "explicit",
        "requested_mode": mode,
        "override_required": False,
    }
    rendered = routes[0].model_dump_json()
    for forbidden in ("PRIVATE_GOAL", "goal", "argv", "path", str(tmp_path)):
        assert forbidden not in rendered


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
    console = Console(record=True, force_terminal=False, width=500)

    cli_module._render_collaboration_report(report, console)

    rendered = console.export_text()
    assert "rejection_limit" in rendered
    assert secret not in rendered
    assert str(tmp_path) not in rendered


def test_collaboration_renderer_uses_safe_shared_execution_evidence_renderer(tmp_path):
    store = ProgramArtifactStore(tmp_path)
    artifact = store.persist(block_name="private", language="python", code="SECRET_CODE = 1\n")
    report = _report(
        execution_evidence=ExecutionEvidence(
            records=(
                ToolExecutionRecord(
                    sequence=1,
                    tool="Exec",
                    status="succeeded",
                    artifact=artifact,
                    role="generator",
                    attempt=1,
                ),
            )
        )
    )
    console = Console(record=True, force_terminal=False, width=500)

    cli_module._render_collaboration_report(report, console, project_root=tmp_path)

    rendered = console.export_text()
    assert str(artifact.local_path) in rendered
    assert "SECRET_CODE" not in rendered
    assert "role=generator attempt=1" in rendered
    store.close()


@pytest.mark.parametrize("mode", ["duo", "triad"])
def test_collaboration_entry_projects_real_generator_program_artifact(tmp_path, mode):
    code = f"{mode}_matrix_value = '\u4e2d'\n"
    candidate = {
        "name": "SubmitCandidate",
        "arguments": {},
    }
    evaluation = {
        "name": "SubmitEvaluation",
        "arguments": {
            "results": [
                {
                    "id": "goal",
                    "passed": True,
                    "observed": "done",
                    "expected": "done",
                    "location": "artifact.txt",
                }
            ]
        },
    }
    scripts = {
        "generator": [
            _reply(
                "\n".join(
                    (
                        "<!-- ToolCall: "
                        + json.dumps({"name": "Exec", "arguments": {"code": code}})
                        + " -->",
                        "<!-- ToolCall: " + json.dumps(candidate) + " -->",
                    )
                )
            )
        ],
        "evaluator": [_reply("<!-- ToolCall: " + json.dumps(evaluation) + " -->")],
    }
    if mode == "triad":
        scripts["planner"] = [
            _reply(
                "<!-- ToolCall: "
                + json.dumps(
                    {
                        "name": "SubmitPlan",
                        "arguments": {
                            "items": [
                                {
                                    "id": "goal",
                                    "behavior": "Run the program",
                                    "acceptance": "The program runs",
                                }
                            ]
                        },
                    }
                )
                + " -->"
            )
        ]

    console = Console(record=True, force_terminal=False, width=500)
    report = run_collaboration_once(
        "PRIVATE_COLLABORATION_GOAL",
        mode=mode,
        tier="trusted",
        model="generator",
        planner_model="planner" if mode == "triad" else None,
        evaluator_model="evaluator",
        max_rejections=2,
        client_factory=lambda model: MockClient(script=list(scripts[model])),
        allowed_root=str(tmp_path),
        console=console,
        plan_confirmer=lambda _summary: True,
    )

    exec_record = next(
        record for record in report.execution_evidence.records if record.tool == "Exec"
    )
    assert report.status == report.stop_reason == "completed"
    assert exec_record.status == "succeeded"
    assert exec_record.role == "generator" and exec_record.attempt == 1
    assert exec_record.artifact is not None and exec_record.artifact.local_path is None
    path = resolve_local_artifact_path(tmp_path, exec_record.artifact.reference)
    assert path is not None and stat.S_ISREG(path.stat().st_mode)
    assert path.read_bytes() == code.encode("utf-8")
    rendered = console.export_text()
    assert str(path) in rendered
    assert code not in rendered
    assert "PRIVATE_COLLABORATION_GOAL" not in rendered


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


def _patch_single_run_dependencies(monkeypatch) -> None:
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: None)
    monkeypatch.setattr(cli_module, "resolve_cli_identity", lambda **kwargs: None)
    monkeypatch.setattr(cli_module, "_load_skill_registry", lambda **kwargs: None)
    monkeypatch.setattr(
        cli_module,
        "run_once",
        lambda _goal, **_kwargs: SimpleNamespace(status=SimpleNamespace(solved=True)),
    )


@pytest.mark.parametrize(
    ("mode_args", "expected_reason", "expected_requested_mode"),
    [([], "default", "default"), (["--mode", "single"], "explicit", "single")],
)
def test_cli_single_routes_once_without_goal_or_invocation_data(
    monkeypatch,
    mode_args,
    expected_reason,
    expected_requested_mode,
):
    _patch_single_run_dependencies(monkeypatch)
    audit_sink = _AuditSink()
    monkeypatch.setattr(
        cli_module,
        "JsonlAuditSink",
        lambda *_args, **_kwargs: pytest.fail("injected audit sink must take priority"),
    )

    assert (
        cli_module.main(
            ["--no-identity", "--no-memory", "run", "PRIVATE_GOAL", *mode_args],
            client_factory=lambda _model: SimpleNamespace(),
            audit_sink=audit_sink,
        )
        == 0
    )

    routes = [event for event in audit_sink.events if event.event_type == "collaboration.route"]
    assert len(routes) == 1
    assert routes[0].parameters == {
        "mode": "single",
        "reason": expected_reason,
        "requested_mode": expected_requested_mode,
        "override_required": False,
    }
    rendered = routes[0].model_dump_json()
    for forbidden in ("PRIVATE_GOAL", "goal", "argv", "path"):
        assert forbidden not in rendered


def test_cli_without_injected_sink_writes_default_route_audit(monkeypatch, tmp_path):
    _patch_single_run_dependencies(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert (
        cli_module.main(
            ["--no-identity", "--no-memory", "run", "PRIVATE_GOAL"],
            client_factory=lambda _model: SimpleNamespace(),
        )
        == 0
    )

    audit_path = tmp_path / ".forgeagent" / "audit.jsonl"
    events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    routes = [event for event in events if event["event_type"] == "collaboration.route"]
    assert len(routes) == 1
    assert routes[0]["parameters"] == {
        "mode": "single",
        "reason": "default",
        "requested_mode": "default",
        "override_required": False,
    }
    assert "PRIVATE_GOAL" not in json.dumps(routes)


def test_cli_default_audit_startup_failure_stops_before_task(monkeypatch, capsys):
    calls: list[str] = []
    _patch_single_run_dependencies(monkeypatch)
    monkeypatch.setattr(
        cli_module,
        "JsonlAuditSink",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("PRIVATE_PATH")),
    )
    monkeypatch.setattr(cli_module, "run_once", lambda goal, **_kwargs: calls.append(goal))

    code = cli_module.main(
        ["--no-identity", "--no-memory", "run", "PRIVATE_GOAL"],
        client_factory=lambda _model: SimpleNamespace(),
    )

    captured = capsys.readouterr()
    assert code == 2
    assert calls == []
    assert "audit startup error" in captured.err
    assert "PRIVATE_PATH" not in captured.err
    assert "PRIVATE_GOAL" not in captured.err


def test_repl_default_single_routes_once_without_goal_or_invocation_data(monkeypatch):
    monkeypatch.setattr(cli_module, "build_mcp_manager", lambda: None)
    monkeypatch.setattr(
        cli_module,
        "run_once",
        lambda _goal, **_kwargs: SimpleNamespace(status=SimpleNamespace(solved=True)),
    )
    audit_sink = _AuditSink()
    inputs = iter(["PRIVATE_GOAL", "quit"])

    repl(
        tier="restricted",
        model="mock",
        client_factory=lambda _model: SimpleNamespace(),
        read_line=lambda _prompt: next(inputs),
        confirmation_available=False,
        no_identity=True,
        no_memory=True,
        use_registry_snapshot=False,
        audit_sink=audit_sink,
    )

    routes = [event for event in audit_sink.events if event.event_type == "collaboration.route"]
    assert len(routes) == 1
    assert routes[0].parameters == {
        "mode": "single",
        "reason": "default",
        "requested_mode": "default",
        "override_required": False,
    }
    rendered = routes[0].model_dump_json()
    for forbidden in ("PRIVATE_GOAL", "goal", "argv", "path"):
        assert forbidden not in rendered
