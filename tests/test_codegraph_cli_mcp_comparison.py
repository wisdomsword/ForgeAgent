from __future__ import annotations

from scripts.codegraph_cli_mcp_comparison import (
    build_context_messages,
    extract_report_fields,
    json_metrics,
    multi_round_context_metrics,
    normalized_text,
    result_metrics,
)

from forgeagent.context import ContextConfig
from forgeagent.models import Role

SAMPLE = """**Exploration: Runtime set_state**

Found 8 symbols across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `set_state` (src/forgeagent/runtime.py:27)
- `readRuntimeChecks` (.claude/skills/comet/scripts/comet-runtime.mjs:8467)

**Source Code**

```python
1\tdef set_state():
2\t    return None
```

**Not shown above — explore these names for their source**

- tests/test_runtime.py: test_set_state
"""


def test_result_metrics_use_singular_file_and_count_sections() -> None:
    assert extract_report_fields(SAMPLE) == {
        "reported_symbols": 8,
        "reported_files": 1,
        "source_line_count": 2,
        "blast_radius_entry_count": 2,
        "not_shown_entry_count": 1,
    }


def test_normalized_text_removes_exactly_one_cli_newline() -> None:
    assert normalized_text(SAMPLE + "\n") == SAMPLE
    assert normalized_text(SAMPLE + "\n\n") == SAMPLE + "\n"


def test_result_and_json_metrics_keep_raw_and_payload_layers_separate() -> None:
    metrics = result_metrics(SAMPLE + "\n", SAMPLE)
    assert metrics["cli_text_bytes"] == len((SAMPLE + "\n").encode())
    assert metrics["mcp_text_bytes"] == len(SAMPLE.encode())
    assert metrics["cli_t_result_raw"] != metrics["mcp_t_result_raw"]
    assert metrics["t_result_normalized"] == metrics["mcp_t_result_raw"]

    payload = [{"type": "text", "text": SAMPLE}]
    wire = json_metrics(payload, SAMPLE)
    assert wire["content_json_bytes"] > wire["text_bytes"]
    assert wire["object_json_bytes"] >= wire["content_json_bytes"]


def test_context_messages_have_two_fixed_messages() -> None:
    messages = build_context_messages("cli", "/repo", "Runtime set_state", 1, SAMPLE)
    assert [message.role for message in messages] == [Role.SYSTEM, Role.USER]
    assert len(messages) == 2
    assert ContextConfig()
    assert "Command: codegraph" in messages[1].content


def test_multi_round_context_metrics_accumulate_history() -> None:
    metrics = multi_round_context_metrics("/repo", "Runtime set_state", 1, SAMPLE, SAMPLE, rounds=3)
    assert metrics["rounds"] == 3
    assert len(metrics["cli_context_round_tokens"]) == 3
    assert len(metrics["mcp_context_round_tokens"]) == 3
    assert metrics["cli_context_round_tokens"][0] < metrics["cli_context_round_tokens"][-1]
    assert metrics["mcp_context_cumulative_tokens"] == sum(metrics["mcp_context_round_tokens"])


def test_mcp_tool_catalog_is_repeated_in_each_round() -> None:
    without_catalog = multi_round_context_metrics(
        "/repo", "Runtime set_state", 1, SAMPLE, SAMPLE, rounds=3
    )
    with_catalog = multi_round_context_metrics(
        "/repo",
        "Runtime set_state",
        1,
        SAMPLE,
        SAMPLE,
        '{"tools":[{"name":"codegraph_explore","inputSchema":{}}]}',
        rounds=3,
    )
    assert with_catalog["mcp_context_round_tokens"][0] > without_catalog[
        "mcp_context_round_tokens"
    ][0]
    assert with_catalog["mcp_context_round_tokens"][2] > without_catalog[
        "mcp_context_round_tokens"
    ][2]
