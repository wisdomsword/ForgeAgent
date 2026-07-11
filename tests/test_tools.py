"""Unit tests for the pluggable ToolRegistry (M7 Phase 1).

Covers the acceptance points in docs/m7-tools-mcp-survey.md §六 Phase 1:
  - registration exposes the tool's arg schema and lookup
  - `default_registry()` ships Exec + Edit
  - the parser recognises tools that are in a passed `tool_schemas`, and still reports
    unknown tools as structured errors (never silently)
  - `parse(text)` with no `tool_schemas` behaves like before M7 (Exec/Edit only)
"""

from pydantic import BaseModel

from forgeagent.executor import TrustedBackend
from forgeagent.policy import CodeAnalyzer
from forgeagent.protocol import (
    EditArgs,
    ExecArgs,
    FileListArgs,
    FileReadArgs,
    FileWriteArgs,
    MCPArgs,
    ParseErrorType,
    SurveyArgs,
    WebFetchArgs,
    parse,
)
from forgeagent.runtime import Runtime
from forgeagent.tools import (
    CodeBlockStore,
    MCPTool,
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


def test_registry_registers_and_exposes_schema():
    registry = ToolRegistry()
    registry.register(_DummyTool())
    assert registry.get("Dummy").name == "Dummy"
    assert registry.arg_schemas() == {"Dummy": _DummyArgs}


def test_registry_get_unknown_returns_none():
    assert ToolRegistry().get("Nope") is None


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

    outcome = tool.run(
        SurveyArgs(question="pick one", options=["a", "b"]), _survey_ctx(asker)
    )
    assert outcome.detail == "a"
    assert seen[0].options == ["a", "b"]


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


def _mcp_ctx(mcp=None, confirmer=None) -> ToolContext:
    return ToolContext(
        blocks=CodeBlockStore(),
        backend=TrustedBackend(),
        runtime=Runtime(),
        analyzer=CodeAnalyzer(),
        mcp=mcp,
        confirmer=confirmer,
    )


def test_mcp_no_manager_is_structured_error():
    outcome = MCPTool().run(MCPArgs(server="s", tool="t"), _mcp_ctx(mcp=None))
    assert outcome.success is False
    assert "no MCP servers" in outcome.detail


def test_mcp_auto_approved_call_skips_gate_and_runs():
    fake = _FakeMCP(auto_approved={("fs", "read_file")})
    # A confirmer that would DENY — proving auto-approve bypasses it entirely.
    ctx = _mcp_ctx(mcp=fake, confirmer=lambda args: False)
    outcome = MCPTool().run(MCPArgs(server="fs", tool="read_file", arguments={"p": "x"}), ctx)
    assert outcome.success is True
    assert fake.calls == [("fs", "read_file", {"p": "x"})]


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


def test_mcp_no_confirmer_denies_non_approved_call():
    # No confirmer wired and not auto-approved -> treated as denial (never silently runs).
    fake = _FakeMCP()
    ctx = _mcp_ctx(mcp=fake, confirmer=None)
    outcome = MCPTool().run(MCPArgs(server="gh", tool="push"), ctx)
    assert outcome.success is False
    assert fake.calls == []
