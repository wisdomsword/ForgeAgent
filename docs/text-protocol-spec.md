# Text Protocol Specification

ForgeAgent exchanges Markdown plus HTML-comment markers. The parser is independent
of vendor function-calling APIs. Text markers and OpenAI-compatible native calls
are normalized into the same `ToolCall` list.

## Code blocks

```markdown
<!-- CodeBlockStart: {"name":"build","path":"optional/file.py"} -->
````python
print("code may contain ```")
````
<!-- CodeBlockEnd: {"name":"build"} -->
```

The actual opening and closing fences must contain the same number of backticks,
at least three. The language word is optional and defaults to `python`; the parsed
`CodeBlock` retains the supplied language, code, name, and optional path. Start and
end marker JSON must be valid, both names are required, and the names must match.
Malformed marker JSON, missing names, mismatches, and invalid block fields become
`ParseError` entries. Matching uses a variable-length fence, so a shorter fence in
the code does not close the block.

## Tool calls and registry

The text form is one JSON object per comment:

```markdown
<!-- ToolCall: {"id":"call-1","name":"FileRead","arguments":{"path":"input.txt"}} -->
```

`id` is optional on input; the parser generates a UUID hex id when absent. `name`
must be in the active `ToolRegistry`; `arguments` defaults to `{}` and is validated
by that tool's Pydantic argument model. Invalid JSON, unknown/missing names, and
schema failures produce `ParseError`, not an exception or silent drop.

The default registry contains `Exec`, `Edit`, `Survey`, `WebFetch`, `FileRead`,
`FileWrite`, and `FileList`. `Skill` is registered when the immutable Skill snapshot
has at least one validated entry. `MCP` is registered only when an MCP manager is
configured. The registry is the single source of truth for parser schemas and
runtime dispatch. `SubTask` is not a protocol tool.

OpenAI-compatible responses may also carry `AssistantMessage.tool_calls`, whose
native entries have `{id, name, arguments}` with `arguments` as a raw JSON string.
`parse(text, native_tool_calls=..., tool_schemas=...)` parses both channels, validates
both through the same registry, and merges them in one `tool_calls` list. Each call
has `source=TEXT` or `source=OPENAI`; dispatch does not branch on source. A malformed
native argument is a recoverable parse error. If native calls are present, Step also
renders them back into ToolCall marker text in assistant history so the next round
can see the prior call.

## Memory candidates

Declarative facts may be proposed with an HTML comment; the marker is removed from
the user-visible body and validated into `ParseResult.memory_candidates`:

```markdown
<!-- Memory: {"scope":"project","kind":"fact","key":"editor","content":"nvim"} -->
```

`scope` is `session` or `project`; `kind` is `fact`, `preference`, `decision`, or
`procedure`. Parsing never writes `MEMORY.md`. The runtime admission gate rejects
procedures, secrets, control characters, and bounded prompt-injection patterns;
procedures are feedback-routed to a future Skill. Malformed JSON or fields become a
recoverable `ParseError`. Users can submit the same structure through the REPL
`/remember <session|project> <key>=<value>` command.

## Current argument contracts

| Tool | Arguments and validation |
| --- | --- |
| `Exec` | `name: str | None`, `code: str | None`, `language: "python"`; at least one of `name` or `code` is required. Inline `code` creates/updates the named block; without `code`, an existing block is executed. |
| `Edit` | `name: str`, non-empty `old: str`, `new: str`, `replace_all: bool = false`. Missing old text or multiple matches without `replace_all` are tool failures. |
| `Survey` | non-empty `question: str`, optional `options: list[str]`. Without an asker or when no interactive channel exists, it returns a terminal `needs_info` outcome. |
| `Skill` | `name: str`; optional `section: "full" | "steps" | "failure_branches" | "completion_criteria" = "full"`. Reads only a validated entry in the current immutable Skill snapshot. Unknown names or unavailable sections are recoverable tool failures. |
| `WebFetch` | `url: str`; GET only, HTTP(S) only, no model-supplied method or headers. In restricted/container it requires confirmation. |
| `FileRead` | `path: str`; canonicalized under `allowed_root`, then secret-masked before feedback. |
| `FileWrite` | `path: str`, `content: str`; canonicalized under `allowed_root`, writes unmasked content, and requires confirmation in restricted/container. |
| `FileList` | `path: str = "."`; lists direct entries only, returned relative to `allowed_root`. |
| `MCP` | non-empty `server: str`, non-empty `tool: str`, `arguments: dict[str, Any] = {}`. The selected MCP server/tool validates its own schema; calls outside `autoApprove` require confirmation. |

Tool failures become `ToolOutcome(success=False)` and are fed back to the model.
WebFetch/File tool failures use fixed text where a URL, host, absolute path, or
exception could disclose sensitive information.

The `Skill` text form follows the same marker grammar. For example, this reads only
the failure branch of a known Skill:

```markdown
<!-- ToolCall: {"id":"call-skill-1","name":"Skill","arguments":{"name":"review-python","section":"failure_branches"}} -->
```

The Skill portion of the initial system prompt has only a bounded catalog of Skill
names and one-line triggers. Full documents are available only through this read-only tool; a truncated
full result directs the model to request `steps`, `failure_branches`, or
`completion_criteria` by name. A Skill document supplies model guidance only: it
does not change confirmation, sandbox, audit, or the two-stage completion rules.

## Front matter and recoverable parsing

Only leading YAML front matter is recognized:

```yaml
---
task_status:
  completed: true
  confidence: 0.9
  status: null
  reason: null
  suggestion: null
---
```

`task_status` fields are `completed: bool`, optional `confidence: float`, optional
`status: refused | need_info | failed`, optional `reason`, and optional
`suggestion`. The parser returns `ParseResult` with `task_status`, `code_blocks`,
`tool_calls`, `errors`, and front-matter-stripped `body`. YAML errors and invalid
task-status fields are recorded as parse errors, while the body is still parsed.

## Completion and terminal status

Completion is deliberately two-stage:

1. A response with any tool call or any parse error cannot complete, even if it also
   declares `completed: true`.
2. Step executes all parsed calls, renders every outcome and parse error as feedback,
   and sends another round.
3. A later clean response with no calls, no parse errors, and `completed: true`
   becomes `Termination.COMPLETED`.

This applies when a tool succeeds and when it fails. A bare `completed: false` is
non-terminal. An explicit `status: refused`, `need_info`, or `failed` is terminal;
the corresponding Step states are `REFUSED`, `NEEDS_INFO`, and `FAILED`. Provider
`stop_reason` values `refusal` and `content_filter` are `REFUSED`; `max_tokens` and
`length` are `TRUNCATED` when the round has no feedback to continue with. A Survey
without an asker is `NEEDS_INFO`. Other mechanical terminal states include
`ANSWERED_IN_PROSE`, `EMPTY_RESPONSE`, `MAX_ROUNDS`, and `CLIENT_ERROR:<kind>`.
These states classify execution; they do not judge whether the answer is correct.

## Confirmation and REPL routing

The protocol does not grant approval. Runtime policy applies confirmation to MCP,
WebFetch, and FileWrite. In `restricted` and `container`, WebFetch and FileWrite
require a TTY confirmer; MCP skips confirmation only for the configured per-server
`autoApprove` entry. Otherwise, missing or non-TTY confirmation rejects the call
without reading input. `FileRead` and `FileList` do not block for confirmation.
`--interactive` controls Survey only.

REPL embedded commands require a slash prefix: `/model` (list or switch model),
`/search`, `/image`, `/mcp`, `/memory`, `/remember`, `/reload`, `/help`, and `/` (command menu). Unknown
slash commands are rejected. Bare `models`, `reload`, `mcp`, and `mcp ...` are
ordinary model goals. The top-level `forgeagent models` CLI subcommand remains a
separate command and is not REPL routing.
