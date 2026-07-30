"""Unit tests for the pluggable ToolRegistry (M7 Phase 1).

Covers the acceptance points in docs/m7-tools-mcp-survey.md §六 Phase 1:
  - registration exposes the tool's arg schema and lookup
  - `default_registry()` ships Exec + Edit
  - the parser recognises tools that are in a passed `tool_schemas`, and still reports
    unknown tools as structured errors (never silently)
  - `parse(text)` with no `tool_schemas` behaves like before M7 (Exec/Edit only)
"""

import pytest
from pydantic import BaseModel

from forgeagent.audit import AuditEvent
from forgeagent.executor import TrustedBackend
from forgeagent.external_actions import ExternalActionReceiptStore, ReceiptError
from forgeagent.headless import HeadlessConfirmer
from forgeagent.policy import CodeAnalyzer
from forgeagent.protocol import (
    EditArgs,
    ExecArgs,
    FileListArgs,
    FileReadArgs,
    FileWriteArgs,
    MCPArgs,
    ParseErrorType,
    SkillArgs,
    SurveyArgs,
    WebFetchArgs,
    parse,
)
from forgeagent.runtime import Runtime
from forgeagent.skills import SkillDefinition, SkillRegistry
from forgeagent.tools import (
    CodeBlockStore,
    ExecTool,
    MCPTool,
    SkillTool,
    SurveyTool,
    Tool,
    ToolContext,
    ToolOutcome,
    ToolRegistry,
    default_registry,
)


class _DummyArgs(BaseModel):
    """A minimal args schema for testing tool registration in isolation."""

    payload: str


class _DummyTool(Tool):
    name = "Dummy"
    args_model = _DummyArgs

    def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutcome:
        assert isinstance(args, _DummyArgs)
        return ToolOutcome(tool="Dummy", success=True, detail=args.payload)


class _RecordingAuditSink:
    def __init__(self):
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> bool:
        self.events.append(event)
        return True


def test_registry_registers_and_exposes_schema():
    registry = ToolRegistry()
    registry.register(_DummyTool())
    assert registry.get("Dummy").name == "Dummy"
    assert registry.arg_schemas() == {"Dummy": _DummyArgs}


def test_registry_get_unknown_returns_none():
    assert ToolRegistry().get("Nope") is None


def test_tool_outcome_completion_defaults_off():
    assert ToolOutcome(tool="Dummy", success=True).completes_task is False


def test_registry_requires_one_registered_completion_tool():
    registry = ToolRegistry()
    registry.register(_DummyTool())

    registry.require_completion("Dummy")

    assert registry.required_completion_tool == "Dummy"
    with pytest.raises(ValueError, match="registered"):
        ToolRegistry().require_completion("Missing")

    class _OtherTool(_DummyTool):
        name = "Other"

    registry.register(_OtherTool())
    with pytest.raises(ValueError, match="already required"):
        registry.require_completion("Other")


def test_default_registry_carries_exec_edit_survey():
    schemas = default_registry().arg_schemas()
    assert schemas == {
        "Exec": ExecArgs,
        "Edit": EditArgs,
        "Survey": SurveyArgs,
        "WebFetch": WebFetchArgs,
        "FileRead": FileReadArgs,
        "FileWrite": FileWriteArgs,
        "FileList": FileListArgs,
    }


def test_registry_later_registration_overrides_earlier():
    class _OtherDummy(_DummyTool):
        pass

    registry = ToolRegistry()
    first = _DummyTool()
    second = _OtherDummy()
    registry.register(first)
    registry.register(second)
    assert registry.get("Dummy") is second


def test_parse_recognises_tool_added_via_tool_schemas():
    # A tool name that is NOT in the built-in Exec/Edit set is accepted when its schema
    # is passed via tool_schemas — this is the extension point MCP/Survey use.
    schemas = {"Dummy": _DummyArgs}
    text = '<!-- ToolCall: {"id": "t1", "name": "Dummy", "arguments": {"payload": "hi"}} -->'
    result = parse(text, tool_schemas=schemas)
    assert not result.errors
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "Dummy"
    assert isinstance(result.tool_calls[0].arguments, _DummyArgs)
    assert result.tool_calls[0].arguments.payload == "hi"


def test_parse_reports_unknown_tool_even_with_extended_schemas():
    # An unknown name is still a structured ParseError under an extended schema set —
    # extension does not soften the "unknown tool must be surfaced" rule.
    schemas = {"Dummy": _DummyArgs}
    text = '<!-- ToolCall: {"id": "t1", "name": "Exec", "arguments": {"code": "1"}} -->'
    result = parse(text, tool_schemas=schemas)
    assert result.tool_calls == []
    assert any(
        e.error_type == ParseErrorType.INVALID_FORMAT
        and "Unknown or missing tool name" in e.message
        for e in result.errors
    )


def test_parse_default_schemas_match_default_registry():
    # `parse(text)` (no tool_schemas) recognises Exec/Edit; the default registry adds
    # Survey on top — upgrading Step to the registry did not shrink the built-in Exec/Edit
    # set, and Survey is only recognised when the registry's schemas are passed.
    text = '<!-- ToolCall: {"id": "t1", "name": "Exec", "arguments": {"code": "1"}} -->'
    default_ok = parse(text)
    registry_ok = parse(text, tool_schemas=default_registry().arg_schemas())
    assert not default_ok.errors and not registry_ok.errors
    assert default_ok.tool_calls[0].name == registry_ok.tool_calls[0].name == "Exec"


def _registry_with_skill(name: str = "review-python") -> SkillRegistry:
    return SkillRegistry(
        {
            name: SkillDefinition(
                name=name,
                trigger="Review Python changes.",
                steps="1. Inspect the diff.",
                failure_branches="Stop when the diff is unavailable.",
                completion_criteria="All findings are recorded.",
                source="user",
            )
        }
    )


def test_skill_tool_returns_requested_section_without_a_confirmer():
    outcome = SkillTool(_registry_with_skill()).run(
        SkillArgs(name="review-python", section="steps"),
        _survey_ctx(),
    )

    assert outcome.success is True
    assert outcome.detail == "1. Inspect the diff."
    assert outcome.continuation == (
        "Skill result truncated; read steps, failure_branches, or completion_criteria by name."
    )
    assert outcome.truncation_mode == "head"


def test_skill_tool_unknown_name_is_recoverable_and_registry_is_conditional():
    registry = _registry_with_skill()
    outcome = SkillTool(registry).run(SkillArgs(name="missing-skill"), _survey_ctx())

    assert (outcome.success, outcome.detail) == (False, "Skill is unavailable")
    assert "Skill" not in default_registry().arg_schemas()
    assert "Skill" not in default_registry(skills=SkillRegistry({})).arg_schemas()
    assert "Skill" in default_registry(skills=registry).arg_schemas()


def test_skill_is_only_parseable_when_its_registry_is_registered():
    text = (
        '<!-- ToolCall: {"id": "t1", "name": "Skill", "arguments": {"name": "review-python"}} -->'
    )

    without_skills = parse(text, tool_schemas=default_registry().arg_schemas())
    with_skills = parse(
        text, tool_schemas=default_registry(skills=_registry_with_skill()).arg_schemas()
    )

    assert without_skills.tool_calls == []
    assert any("Unknown or missing tool name" in error.message for error in without_skills.errors)
    assert not with_skills.errors
    assert isinstance(with_skills.tool_calls[0].arguments, SkillArgs)


# --- Survey tool (M7 Phase 2) ------------------------------------------------


def _survey_ctx(asker=None) -> ToolContext:
    return ToolContext(
        blocks=CodeBlockStore(),
        backend=TrustedBackend(),
        runtime=Runtime(),
        analyzer=CodeAnalyzer(),
        asker=asker,
    )


def test_survey_with_asker_feeds_answer_back():
    # An answer from the asker becomes the tool's feedback detail for the next round.
    tool = SurveyTool()
    seen: list[SurveyArgs] = []

    def asker(args: SurveyArgs) -> str:
        seen.append(args)
        return "blue"

    outcome = tool.run(SurveyArgs(question="favourite colour?"), _survey_ctx(asker))
    assert outcome.success is True
    assert outcome.needs_info is False
    assert outcome.detail == "blue"
    assert seen[0].question == "favourite colour?"


def test_survey_without_asker_signals_needs_info():
    # Headless (no asker): the tool marks needs_info and carries the question as detail.
    outcome = SurveyTool().run(SurveyArgs(question="which file?"), _survey_ctx(asker=None))
    assert outcome.success is False
    assert outcome.needs_info is True
    assert outcome.detail == "which file?"


def test_survey_asker_returning_none_signals_needs_info():
    # Asker present but no answer (declined / no channel) also degrades to needs_info.
    outcome = SurveyTool().run(
        SurveyArgs(question="proceed?"), _survey_ctx(asker=lambda args: None)
    )
    assert outcome.needs_info is True
    assert outcome.detail == "proceed?"


def test_survey_options_passed_through_to_asker():
    tool = SurveyTool()
    seen: list[SurveyArgs] = []

    def asker(args: SurveyArgs) -> str:
        seen.append(args)
        return args.options[0]

    outcome = tool.run(SurveyArgs(question="pick one", options=["a", "b"]), _survey_ctx(asker))
    assert outcome.detail == "a"
    assert seen[0].options == ["a", "b"]


def test_exec_success_and_failure_use_same_tail_continuation():
    success = ExecTool().run(ExecArgs(code="print('done')"), _survey_ctx())
    failure = ExecTool().run(ExecArgs(code="raise RuntimeError('boom')"), _survey_ctx())

    assert success.success is True
    assert failure.success is False
    assert success.truncation_mode == failure.truncation_mode == "tail"
    assert success.continuation == failure.continuation
    assert success.continuation == "请缩小输出范围，或将工作分片执行后重试"


def test_survey_uses_honest_head_continuation():
    survey_outcome = SurveyTool().run(
        SurveyArgs(question="which file?"), _survey_ctx(asker=lambda args: "report.txt")
    )

    assert survey_outcome.truncation_mode == "head"
    assert survey_outcome.continuation == "此工具不保留游标；如需更多结果，请重新提问"


# --- MCP tool confirmation gate (M7 Phase 3) ---------------------------------
# These exercise MCPTool.run's gate logic with a tiny fake manager, so no real MCP
# server is launched (the real discover/call path is covered in test_mcp_manager.py).


class _FakeMCP:
    """Minimal stand-in for MCPManager: records calls, controls auto-approve."""

    def __init__(self, *, auto_approved: set[tuple[str, str]] | None = None):
        self._auto = auto_approved or set()
        self.calls: list[tuple[str, str, dict]] = []

    def is_auto_approved(self, server: str, tool: str) -> bool:
        return (server, tool) in self._auto

    def call_tool(self, server: str, tool: str, arguments: dict) -> dict:
        self.calls.append((server, tool, arguments))
        return {"ok": True, "text": f"{server}:{tool} ran"}


class _ReceiptMCP(_FakeMCP):
    def __init__(self, result: dict, **kwargs):
        super().__init__(**kwargs)
        self.result = result

    def call_tool(self, server: str, tool: str, arguments: dict) -> dict:
        self.calls.append((server, tool, arguments))
        return self.result


def _mcp_ctx(
    mcp=None,
    confirmer=None,
    *,
    allow_auto_approve=True,
    receipt_store=None,
    task_id=None,
    operation_id=None,
) -> ToolContext:
    return ToolContext(
        blocks=CodeBlockStore(),
        backend=TrustedBackend(),
        runtime=Runtime(),
        analyzer=CodeAnalyzer(),
        mcp=mcp,
        confirmer=confirmer,
        allow_auto_approve=allow_auto_approve,
        receipt_store=receipt_store,
        task_id=task_id,
        operation_id=operation_id,
    )


def _receipt_store(tmp_path, task_id="task-receipt"):
    return ExternalActionReceiptStore(str(tmp_path), task_id=task_id)


def test_mcp_protected_dispatch_without_receipt_store_fails_closed():
    fake = _ReceiptMCP({"ok": True, "text": "should not run", "dispatch_certainty": "confirmed"})
    outcome = MCPTool().run(
        MCPArgs(server="gh", tool="create_issue"),
        _mcp_ctx(mcp=fake, confirmer=lambda args: True, task_id="task-receipt"),
    )
    assert outcome.success is False
    assert outcome.detail == "MCP receipt unavailable"
    assert fake.calls == []


def test_mcp_protected_call_receipts_cover_confirmed_protocol_error_and_unknown(tmp_path):
    for index, (result, expected_phase, expected_success, expected_detail) in enumerate(
        (
            (
                {"ok": True, "text": "done", "dispatch_certainty": "confirmed"},
                "confirmed",
                True,
                "done",
            ),
            (
                {"ok": False, "text": "protocol error", "dispatch_certainty": "confirmed"},
                "confirmed",
                False,
                "protocol error",
            ),
            (
                {"ok": False, "text": "MCP call failed", "dispatch_certainty": "unknown"},
                "unknown",
                False,
                "MCP result unknown; reconcile the external action before retrying",
            ),
        )
    ):
        root = tmp_path / f"{expected_phase}-{index}"
        root.mkdir(exist_ok=True)
        store = _receipt_store(root)
        fake = _ReceiptMCP(result)
        ctx = _mcp_ctx(
            mcp=fake,
            confirmer=lambda args: True,
            receipt_store=store,
            task_id="task-receipt",
            operation_id="model-generated-id",
        )
        outcome = MCPTool().run(MCPArgs(server="gh", tool="create_issue"), ctx)
        assert outcome.success is expected_success
        assert outcome.detail == expected_detail
        pending = store.list_pending(task_id="task-receipt")
        assert len(pending) == 1
        assert pending[0].phase == expected_phase


def test_mcp_receipt_transition_failure_blocks_manager_entry(tmp_path, monkeypatch):
    store = _receipt_store(tmp_path)
    fake = _ReceiptMCP({"ok": True, "text": "should not run", "dispatch_certainty": "confirmed"})
    monkeypatch.setattr(
        store, "mark_dispatched", lambda *args: (_ for _ in ()).throw(ReceiptError("boom"))
    )
    outcome = MCPTool().run(
        MCPArgs(server="gh", tool="create_issue"),
        _mcp_ctx(
            mcp=fake, confirmer=lambda args: True, receipt_store=store, task_id="task-receipt"
        ),
    )
    assert outcome.success is False
    assert outcome.detail == "MCP receipt unavailable"
    assert fake.calls == []


def test_mcp_auto_approve_and_denial_do_not_create_receipts(tmp_path):
    store = _receipt_store(tmp_path)
    auto = _ReceiptMCP(
        {"ok": True, "text": "done", "dispatch_certainty": "confirmed"},
        auto_approved={("fs", "read_file")},
    )
    auto_outcome = MCPTool().run(
        MCPArgs(server="fs", tool="read_file"),
        _mcp_ctx(
            mcp=auto, confirmer=lambda args: False, receipt_store=store, task_id="task-receipt"
        ),
    )
    denied = _ReceiptMCP({"ok": True, "text": "should not run", "dispatch_certainty": "confirmed"})
    denied_outcome = MCPTool().run(
        MCPArgs(server="gh", tool="delete_repo"),
        _mcp_ctx(
            mcp=denied, confirmer=lambda args: False, receipt_store=store, task_id="task-receipt"
        ),
    )
    assert auto_outcome.success is True and denied_outcome.success is False
    assert auto.calls and denied.calls == []
    assert store.list_pending(task_id="task-receipt") == ()


def test_mcp_no_manager_is_structured_error():
    outcome = MCPTool().run(MCPArgs(server="s", tool="t"), _mcp_ctx(mcp=None))
    assert outcome.success is False
    assert "no MCP servers" in outcome.detail


def test_mcp_uses_honest_head_continuation():
    outcome = MCPTool().run(
        MCPArgs(server="fs", tool="read_file"),
        _mcp_ctx(mcp=_FakeMCP(auto_approved={("fs", "read_file")})),
    )

    assert outcome.truncation_mode == "head"
    assert outcome.continuation == "此工具不保留游标；如需更多结果，请缩小查询参数后重新调用"


def test_mcp_auto_approved_call_skips_gate_and_runs():
    fake = _FakeMCP(auto_approved={("fs", "read_file")})
    # A confirmer that would DENY — proving auto-approve bypasses it entirely.
    ctx = _mcp_ctx(mcp=fake, confirmer=lambda args: False)
    outcome = MCPTool().run(MCPArgs(server="fs", tool="read_file", arguments={"p": "x"}), ctx)
    assert outcome.success is True
    assert fake.calls == [("fs", "read_file", {"p": "x"})]


def test_http_context_does_not_inherit_mcp_auto_approval() -> None:
    class _AutoApproveMustNotBeRead(_FakeMCP):
        def is_auto_approved(self, server: str, tool: str) -> bool:
            raise AssertionError("HTTP context must not read MCP autoApprove")

    fake = _AutoApproveMustNotBeRead(auto_approved={("fs", "write_file")})
    sink = _RecordingAuditSink()
    confirmer = HeadlessConfirmer([], audit=sink)
    ctx = _mcp_ctx(mcp=fake, confirmer=confirmer, allow_auto_approve=False)
    ctx.audit_sink = sink
    ctx.task_id = "http-task"
    ctx.operation_id = "http-tool-call-denied"

    outcome = MCPTool().run(MCPArgs(server="fs", tool="write_file"), ctx)

    assert outcome.success is False
    assert fake.calls == []
    assert len(sink.events) == 1
    assert sink.events[0].result_status == "denied"
    assert sink.events[0].operation_id == "http-tool-call-denied"


def test_http_allowlist_preapproval_uses_tool_operation_id_once() -> None:
    fake = _FakeMCP()
    sink = _RecordingAuditSink()
    confirmer = HeadlessConfirmer({"mcp/fs/write_file"}, audit=sink)
    import tempfile

    ctx = _mcp_ctx(
        mcp=fake,
        confirmer=confirmer,
        allow_auto_approve=False,
        receipt_store=ExternalActionReceiptStore(tempfile.mkdtemp(), task_id="http-task"),
        task_id="http-task",
    )
    ctx.audit_sink = sink
    ctx.task_id = "http-task"
    ctx.operation_id = "http-tool-call-preapproved"

    outcome = MCPTool().run(MCPArgs(server="fs", tool="write_file"), ctx)

    assert outcome.success is True
    assert fake.calls == [("fs", "write_file", {})]
    assert sink.events[0].result_status == "preapproved"
    assert sink.events[0].operation_id == "http-tool-call-preapproved"


def test_http_headless_mcp_denial_names_allowlist_not_user() -> None:
    fake = _FakeMCP()
    confirmer = HeadlessConfirmer([], audit=None)
    ctx = _mcp_ctx(mcp=fake, confirmer=confirmer, allow_auto_approve=False)

    outcome = MCPTool().run(MCPArgs(server="fs", tool="write_file"), ctx)

    assert outcome.success is False
    assert outcome.detail == "rejected: operation is not in the headless allowlist"
    assert fake.calls == []


def test_mcp_non_approved_call_needs_confirmer_yes():
    fake = _FakeMCP()
    seen: list[MCPArgs] = []

    def confirmer(args: MCPArgs) -> bool:
        seen.append(args)
        return True

    ctx = _mcp_ctx(mcp=fake, confirmer=confirmer)
    outcome = MCPTool().run(MCPArgs(server="gh", tool="create_issue"), ctx)
    assert outcome.success is True
    assert fake.calls and fake.calls[0][:2] == ("gh", "create_issue")
    assert seen[0].tool == "create_issue"  # the gate saw the call


def test_mcp_confirmer_denial_blocks_call():
    fake = _FakeMCP()
    ctx = _mcp_ctx(mcp=fake, confirmer=lambda args: False)
    outcome = MCPTool().run(MCPArgs(server="gh", tool="delete_repo"), ctx)
    assert outcome.success is False
    assert "not approved" in outcome.detail
    assert fake.calls == []  # denied -> server never called


def test_mcp_confirmation_decision_is_audited_once():
    fake = _FakeMCP()
    sink = _RecordingAuditSink()
    ctx = _mcp_ctx(mcp=fake, confirmer=lambda args: False)
    ctx.audit_sink = sink
    ctx.task_id = "task-confirmation"
    ctx.operation_id = "tool-call-denied"

    outcome = MCPTool().run(MCPArgs(server="gh", tool="delete_repo"), ctx)

    assert outcome.success is False
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.event_type == "confirmation.decision"
    assert event.task_id == "task-confirmation"
    assert event.operation_id == "tool-call-denied"
    assert event.result_status == "denied"
    assert event.parameters == {
        "tool": "MCP",
        "server": "gh",
        "operation": "delete_repo",
    }


def test_mcp_auto_approve_emits_preapproved_decision():
    fake = _FakeMCP(auto_approved={("fs", "read_file")})
    sink = _RecordingAuditSink()
    ctx = _mcp_ctx(mcp=fake, confirmer=None)
    ctx.audit_sink = sink
    ctx.operation_id = "tool-call-preapproved"

    outcome = MCPTool().run(MCPArgs(server="fs", tool="read_file"), ctx)

    assert outcome.success is True
    assert len(sink.events) == 1
    assert sink.events[0].result_status == "preapproved"
    assert sink.events[0].operation_id == "tool-call-preapproved"
    assert sink.events[0].duration_ms == 0


def test_confirmer_exception_emits_correlated_error_decision_and_reraises():
    fake = _FakeMCP()
    sink = _RecordingAuditSink()
    control = RuntimeError("private confirmer failure")

    def confirmer(args):
        raise control

    ctx = _mcp_ctx(mcp=fake, confirmer=confirmer)
    ctx.audit_sink = sink
    ctx.operation_id = "tool-call-error"

    with pytest.raises(RuntimeError) as raised:
        MCPTool().run(MCPArgs(server="gh", tool="delete_repo"), ctx)

    assert raised.value is control
    assert len(sink.events) == 1
    assert sink.events[0].operation_id == "tool-call-error"
    assert sink.events[0].result_status == "error"
    assert sink.events[0].parameters == {
        "tool": "MCP",
        "server": "gh",
        "operation": "delete_repo",
    }


def test_mcp_outcome_uses_public_identity_but_routes_raw_identity(monkeypatch):
    import forgeagent.mcp_manager as mcp_manager_module
    from forgeagent.mcp_manager import MCPManager, MCPServerConfig

    server_secret = "feedback-server-secret"
    tool_secret = "feedback-tool-secret"
    server = f"external-{server_secret}"
    tool = f"read-{tool_secret}"
    monkeypatch.setattr(
        mcp_manager_module,
        "sensitive_env_values",
        lambda: {server_secret, tool_secret},
    )
    manager = MCPManager({server: MCPServerConfig(command="unused")})
    seen: list[tuple[str, str]] = []
    original_auto_approved = manager.is_auto_approved

    def is_auto_approved(raw_server: str, raw_tool: str) -> bool:
        seen.append((raw_server, raw_tool))
        return original_auto_approved(raw_server, raw_tool)

    monkeypatch.setattr(manager, "is_auto_approved", is_auto_approved)
    outcome = MCPTool().run(
        MCPArgs(server=server, tool=tool),
        _mcp_ctx(mcp=manager, confirmer=lambda args: False),
    )

    assert seen == [(server, tool)]
    assert outcome.success is False
    assert server_secret not in outcome.block_name
    assert tool_secret not in outcome.block_name
    assert server_secret not in outcome.detail
    assert tool_secret not in outcome.detail
    assert "***REDACTED***" in outcome.block_name


def test_mcp_call_failure_uses_public_identity_but_calls_raw_identity(monkeypatch):
    import forgeagent.mcp_manager as mcp_manager_module
    from forgeagent.mcp_manager import MCPManager, MCPServerConfig

    secret = "call-feedback-secret"
    server = f"external-{secret}"
    tool = f"read-{secret}"
    monkeypatch.setattr(mcp_manager_module, "sensitive_env_values", lambda: {secret})
    manager = MCPManager({server: MCPServerConfig(command="unused")})
    calls: list[tuple[str, str, dict]] = []
    original_call = manager.call_tool

    def call_tool(raw_server: str, raw_tool: str, arguments: dict):
        calls.append((raw_server, raw_tool, arguments))
        return original_call(raw_server, raw_tool, arguments)

    monkeypatch.setattr(manager, "call_tool", call_tool)
    outcome = MCPTool().run(
        MCPArgs(server=server, tool=tool, arguments={"value": "safe"}),
        _mcp_ctx(mcp=manager, confirmer=lambda args: True),
    )

    assert calls == [(server, tool, {"value": "safe"})]
    assert outcome.success is False
    assert secret not in outcome.block_name
    assert secret not in outcome.detail
    assert "***REDACTED***" in outcome.block_name
    assert "***REDACTED***" in outcome.detail


def test_mcp_unknown_outcome_uses_fixed_collision_free_category_and_routes_raw_identity():
    from forgeagent.mcp_manager import MCPManager, MCPServerConfig

    manager = MCPManager({"unknown": MCPServerConfig(command="unused")})
    calls: list[tuple[str, str, dict]] = []
    original_call = manager.call_tool

    def call_tool(raw_server: str, raw_tool: str, arguments: dict):
        calls.append((raw_server, raw_tool, arguments))
        return original_call(raw_server, raw_tool, arguments)

    manager.call_tool = call_tool
    outcome = MCPTool().run(
        MCPArgs(server="manual-raw-server", tool="echo", arguments={"value": "safe"}),
        _mcp_ctx(mcp=manager, confirmer=lambda args: True),
    )

    assert calls == [("manual-raw-server", "echo", {"value": "safe"})]
    assert outcome.success is False
    assert outcome.block_name == "unknown #2:echo"
    assert outcome.detail == "unknown MCP server 'unknown #2'"
    assert "manual-raw-server" not in outcome.block_name
    assert "manual-raw-server" not in outcome.detail


def test_mcp_no_manager_outcome_masks_known_identity(monkeypatch):
    import forgeagent.tools as tools_module

    secret = "no-manager-secret"
    monkeypatch.setattr(tools_module, "sensitive_env_values", lambda: {secret})

    outcome = MCPTool().run(
        MCPArgs(server=f"external-{secret}", tool=f"read-{secret}"),
        _mcp_ctx(mcp=None),
    )

    assert secret not in outcome.block_name
    assert "***REDACTED***" in outcome.block_name


def test_mcp_no_confirmer_denies_non_approved_call():
    # No confirmer wired and not auto-approved -> treated as denial (never silently runs).
    fake = _FakeMCP()
    ctx = _mcp_ctx(mcp=fake, confirmer=None)
    outcome = MCPTool().run(MCPArgs(server="gh", tool="push"), ctx)
    assert outcome.success is False
    assert outcome.detail == "rejected: no interactive confirmation channel available"
    assert fake.calls == []
