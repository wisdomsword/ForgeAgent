"""Unit tests for the text protocol parser (M2-5).

Covers the testability checklist in docs/text-protocol-spec.md. Note: the Edit tool's
old-string matching / replace_all-multiple behavior is a *runtime* concern of the tool
processor (M3), not the parser — the parser only validates the Edit argument schema.
That runtime assertion is deferred to M3; here we assert the schema parses.
"""

import pytest
from pydantic import ValidationError

from forgeagent.models import NativeToolCall
from forgeagent.protocol import (
    EditArgs,
    ExecArgs,
    MemoryCandidate,
    ParseErrorType,
    SkillArgs,
    ToolCallSource,
    parse,
)


def test_exec_happy_path():
    text = '<!-- ToolCall: {"id": "t1", "name": "Exec", "arguments": {"code": "print(1)"}} -->'
    result = parse(text)
    assert not result.errors
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.name == "Exec"
    assert isinstance(call.arguments, ExecArgs)
    assert call.arguments.code == "print(1)"


def test_edit_happy_path():
    text = (
        '<!-- ToolCall: {"id": "t2", "name": "Edit", '
        '"arguments": {"name": "blk", "old": "a", "new": "b"}} -->'
    )
    result = parse(text)
    assert not result.errors
    assert len(result.tool_calls) == 1
    assert isinstance(result.tool_calls[0].arguments, EditArgs)
    assert result.tool_calls[0].arguments.replace_all is False


def test_skill_args_accepts_catalog_name_and_declared_section():
    assert SkillArgs(name="review-python").section == "full"
    assert SkillArgs(name="review-python", section="failure_branches").section == "failure_branches"
    with pytest.raises(ValidationError):
        SkillArgs(name="../review-python")
    with pytest.raises(ValidationError):
        SkillArgs(name="review-python", section="trigger")


def test_code_block_happy_path():
    text = (
        '<!-- CodeBlockStart: {"name": "hello"} -->\n'
        "```python\n"
        "print('hi')\n"
        "```\n"
        '<!-- CodeBlockEnd: {"name": "hello"} -->'
    )
    result = parse(text)
    assert not result.errors
    assert len(result.code_blocks) == 1
    assert result.code_blocks[0].name == "hello"
    assert "print('hi')" in result.code_blocks[0].code


def test_code_block_with_embedded_triple_backticks():
    # The code itself contains a ``` fence; variable-length outer fence (4 ticks)
    # must not close early (Y3).
    text = (
        '<!-- CodeBlockStart: {"name": "md"} -->\n'
        "````python\n"
        'doc = """\n```\ninner\n```\n"""\n'
        "````\n"
        '<!-- CodeBlockEnd: {"name": "md"} -->'
    )
    result = parse(text)
    assert not result.errors
    assert len(result.code_blocks) == 1
    assert "inner" in result.code_blocks[0].code
    assert "```" in result.code_blocks[0].code  # inner fence preserved


def test_malformed_json_in_toolcall_produces_error_not_crash():
    text = '<!-- ToolCall: {"id": "t1", "name": "Exec", "arguments": {"code": "x",}} -->'
    result = parse(text)
    assert result.tool_calls == []
    assert any(e.error_type == ParseErrorType.JSON_DECODE_ERROR for e in result.errors)


def test_code_block_name_mismatch_reported_and_skipped():
    text = (
        '<!-- CodeBlockStart: {"name": "a"} -->\n```python\nx=1\n```\n'
        '<!-- CodeBlockEnd: {"name": "b"} -->\n'
        '<!-- CodeBlockStart: {"name": "ok"} -->\n```python\ny=2\n```\n'
        '<!-- CodeBlockEnd: {"name": "ok"} -->'
    )
    result = parse(text)
    # First block errors; second still parses.
    assert any(e.error_type == ParseErrorType.INVALID_FORMAT for e in result.errors)
    assert [b.name for b in result.code_blocks] == ["ok"]


def test_exec_requires_name_or_code():
    text = '<!-- ToolCall: {"id": "t1", "name": "Exec", "arguments": {}} -->'
    result = parse(text)
    assert result.tool_calls == []
    assert any(e.error_type == ParseErrorType.VALIDATION_ERROR for e in result.errors)


def test_edit_schema_requires_fields():
    # Missing 'old' -> validation error (schema-level; runtime matching is M3).
    text = '<!-- ToolCall: {"id": "t1", "name": "Edit", "arguments": {"name": "b", "new": "x"}} -->'
    result = parse(text)
    assert result.tool_calls == []
    assert any(e.error_type == ParseErrorType.VALIDATION_ERROR for e in result.errors)


def test_unknown_tool_name_reported_not_silent():
    text = '<!-- ToolCall: {"id": "t1", "name": "MCP", "arguments": {}} -->'
    result = parse(text)
    assert result.tool_calls == []
    assert any("Unknown or missing tool name" in e.message for e in result.errors)


def test_front_matter_absent_parses_body():
    text = '<!-- ToolCall: {"id": "t1", "name": "Exec", "arguments": {"code": "1"}} -->'
    result = parse(text)
    assert result.task_status is None
    assert len(result.tool_calls) == 1


def test_memory_marker_is_extracted_and_removed_from_body():
    text = (
        'answer <!-- Memory: {"scope":"project","kind":"fact","key":"editor","content":"vim"} -->'
    )
    result = parse(text)
    assert not result.errors
    assert result.memory_candidates == [
        MemoryCandidate(scope="project", kind="fact", key="editor", content="vim")
    ]
    assert "Memory:" not in result.body


def test_malformed_memory_marker_produces_error_without_candidate():
    result = parse('x <!-- Memory: {"scope":"project","key":"missing-kind"} -->')
    assert result.memory_candidates == []
    assert any(error.error_type == ParseErrorType.VALIDATION_ERROR for error in result.errors)


def test_memory_content_may_contain_json_braces():
    result = parse(
        'x <!-- Memory: {"scope":"session","kind":"fact",'
        '"key":"json","content":"value with } brace"} -->'
    )
    assert result.memory_candidates[0].content == "value with } brace"
    assert not result.errors


def test_front_matter_present_and_valid():
    text = "---\ntask_status:\n  completed: true\n  confidence: 0.9\n---\nAll done."
    result = parse(text)
    assert result.task_status is not None
    assert result.task_status.completed is True
    assert result.task_status.confidence == 0.9


def test_front_matter_malformed_records_error_but_parses_body():
    text = (
        "---\n"
        "task_status: {completed: not_a_bool}\n"
        "---\n"
        '<!-- ToolCall: {"id": "t1", "name": "Exec", "arguments": {"code": "1"}} -->'
    )
    result = parse(text)
    # Body still parsed despite bad front matter.
    assert len(result.tool_calls) == 1
    assert any(e.error_type == ParseErrorType.VALIDATION_ERROR for e in result.errors)


def test_toolcall_missing_id_gets_generated():
    text = '<!-- ToolCall: {"name": "Exec", "arguments": {"code": "1"}} -->'
    result = parse(text)
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id  # auto-generated uuid


def test_text_channel_tool_calls_are_tagged_source_text():
    text = '<!-- ToolCall: {"id": "t1", "name": "Exec", "arguments": {"code": "1"}} -->'
    result = parse(text)
    assert result.tool_calls[0].source == ToolCallSource.TEXT


# --- native tool_calls channel (ToolSource.OPENAI, M6) ------------------------


def test_native_exec_happy_path():
    native = [NativeToolCall(id="c1", name="Exec", arguments='{"code": "print(1)"}')]
    result = parse("", native_tool_calls=native)
    assert not result.errors
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.id == "c1"
    assert call.name == "Exec"
    assert isinstance(call.arguments, ExecArgs)
    assert call.arguments.code == "print(1)"
    assert call.source == ToolCallSource.OPENAI


def test_native_edit_happy_path():
    native = [
        NativeToolCall(id="c2", name="Edit", arguments='{"name": "blk", "old": "a", "new": "b"}')
    ]
    result = parse("", native_tool_calls=native)
    assert not result.errors
    assert isinstance(result.tool_calls[0].arguments, EditArgs)


def test_native_malformed_json_arguments_produces_error_not_crash():
    native = [NativeToolCall(id="c1", name="Exec", arguments='{"code": "x",}')]
    result = parse("", native_tool_calls=native)
    assert result.tool_calls == []
    assert any(e.error_type == ParseErrorType.JSON_DECODE_ERROR for e in result.errors)


def test_native_unknown_tool_name_reported_not_silent():
    native = [NativeToolCall(id="c1", name="MCP", arguments="{}")]
    result = parse("", native_tool_calls=native)
    assert result.tool_calls == []
    assert any("Unknown or missing tool name" in e.message for e in result.errors)


def test_native_exec_requires_name_or_code():
    native = [NativeToolCall(id="c1", name="Exec", arguments="{}")]
    result = parse("", native_tool_calls=native)
    assert result.tool_calls == []
    assert any(e.error_type == ParseErrorType.VALIDATION_ERROR for e in result.errors)


def test_both_channels_merge_into_one_tool_calls_list():
    text = '<!-- ToolCall: {"id": "t1", "name": "Exec", "arguments": {"code": "1"}} -->'
    native = [
        NativeToolCall(id="c1", name="Edit", arguments='{"name": "b", "old": "a", "new": "z"}')
    ]
    result = parse(text, native_tool_calls=native)
    assert len(result.tool_calls) == 2
    sources = {call.source for call in result.tool_calls}
    assert sources == {ToolCallSource.TEXT, ToolCallSource.OPENAI}


def test_no_native_tool_calls_is_equivalent_to_omitting_argument():
    text = '<!-- ToolCall: {"id": "t1", "name": "Exec", "arguments": {"code": "1"}} -->'
    assert parse(text) == parse(text, native_tool_calls=[])
