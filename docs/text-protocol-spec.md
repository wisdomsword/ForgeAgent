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

## Loop checkpoint contract

M21 Loop uses the separate durable schema `forgeagent.loop.v1`; it is not a normal
Task protocol marker and does not alter ordinary Task completion. A Loop 专用
`Checkpoint` tool is available only inside a Loop Task. Its arguments are bounded
`completed_items`, `open_questions`, and `handoff` data. A successful result means
the complete checkpoint was atomically committed with a new revision before feedback
returns to the model. The tool must not be treated as task completion: a later clean
response still needs the normal two-stage Task completion contract.

Checkpoint content is untrusted persisted data. On resume it is rendered with fixed
bounds and framing, so it is usable as handoff/replay context but never grants
permissions or overrides the current server/CLI sandbox, root, identity, confirmer,
credentials, or MCP policy. A resume uses the checkpoint's frozen goal and budgets;
callers cannot pass replacements. A crash can replay work since the last successful
Checkpoint commit, so callers must not assume exactly-once external side effects.

The public Loop report uses only the stable schema, id, status, counters and one of
these stop reasons: `completed`, `cancelled`, `wall_clock`,
`token_usage_unavailable`, `token_budget`, `max_rounds`, `consecutive_failures`,
`unrecoverable_failure`, or `checkpoint_error`. `wall_clock` is cooperative: an
in-flight model or tool call is not force-killed, and the stop is observed at the
next safe boundary. M20 Evaluator is not part of the Loop protocol. An M22
collaborative Loop freezes `collaboration_mode`, `collaboration_id`, and (after
confirmation) `plan_digest` as additive `forgeagent.loop.v1` fields. Old checkpoints
without them remain single. Resume rejects mode or digest drift instead of replacing
the accepted completion standard.

## Runtime collaboration contract

M22 runtime collaboration uses the separate durable schema
`forgeagent.collaboration.v1`. It is a Task-level controller, not a new model-output
marker and not a change to ordinary `TaskStatus`/`TaskOutcome`.

In Duo, ForgeAgent creates one fixed `goal` acceptance item, then runs fresh
Generator and Evaluator Tasks. In Triad, a fresh Planner first calls `SubmitPlan` with
bounded, unique `{id, behavior, acceptance}` items. The plan is normalized and hashed;
an interactive confirmer or server-owned headless policy must approve it before the
Generator starts. Confirmation freezes the items, their order and `plan_digest`.

Generator must call the zero-argument `SubmitCandidate` tool to submit the current
attempt; ordinary prose or `task_status.completed` does not advance the collaboration.
The Evaluator receives the original goal as framed task data, the frozen acceptance
items, and access to observable artifacts. It must call `SubmitEvaluation` with exactly
one bounded result for every frozen ID. Successful `SubmitPlan`, `SubmitCandidate`, and
`SubmitEvaluation` calls immediately complete their role without a later standalone
completion response. Only a complete all-pass verdict makes the collaboration
`completed`. A rejection starts a fresh Generator with bounded evidence until
`max_rejections` is exhausted.

Role tool registries are deliberately asymmetric:

- Planner: `SubmitPlan` only.
- Generator: the caller-owned ordinary task registry plus `SubmitCandidate`.
- Evaluator: `FileRead`, `FileList`, and `SubmitEvaluation` only; no Exec, FileWrite,
  Edit, WebFetch, MCP, Skill, Survey, or Memory state. A caller-approved immutable
  identity prompt may still be composed for the fresh Task; role conversation and
  mutable runtime state are not shared.

The public collaboration report contains only stable fields: `collaboration_id`,
mode, status, stop reason, phase, `plan_item_count`, `passed_item_count`,
`failed_item_count`, `generator_attempts`, `evaluator_attempts`, `rejections`, rounds,
normalized usage, `usage_available`, and bounded masked evidence summaries. Full goal,
plan/verdict text, prompts, raw replies, tool arguments, artifact contents, credentials
and absolute host paths remain private. Stable stop classes include confirmation,
rejection limit, invalid role submission, role/configuration failure, state failure and
cooperative cancellation.

The collaboration state and tool payloads are untrusted persisted/task data. JSON
framing, strict Pydantic validation, secret masking and text bounds do not grant them
instruction authority or expand the selected sandbox, confirmer, root, model or tool
registry.

## Independent Evaluator result

显式 `forgeagent evaluate` 使用独立的专用 YAML 合同，不复用 Generator 的前置 front
matter：

```yaml
evaluator_result:
  status: passed | failed
  observed_evidence:
    - bounded statement
  unmet_expectations:
    - bounded statement
```

该结果只由独立 Evaluator facade 解析，字段、条数和文本长度均受限；畸形或额外字段按
固定失败处理。它不能设置或改变 `TaskStatus`，也不能绕过标准 Task 的两阶段完成语义。
普通 Generator 仍必须先执行并反馈工具调用，再由后续无调用、无解析错误且声明完成的
干净响应进入 `Termination.COMPLETED`。

普通 Task 到达正常终态时会向已配置的 audit sink 写一条固定 `task.outcome` 事件，只含
`completed` 和 `round_count`。M20 指标聚合可从该事件计算首轮正确率与修正轮数；缺失或
畸形事件保持 `null`，不会从模型 prose 或 provider stop reason 猜测完成状态。

## Confirmation and REPL routing

The protocol does not grant approval. Runtime policy applies confirmation to MCP,
WebFetch, and FileWrite. In `restricted` and `container`, WebFetch and FileWrite
require a TTY confirmer; MCP skips confirmation only for the configured per-server
`autoApprove` entry. Otherwise, missing or non-TTY confirmation rejects the call
without reading input. `FileRead` and `FileList` do not block for confirmation.
`--interactive` controls Survey only.

REPL embedded commands require a slash prefix: `/duo`, `/triad`, `/model` (list or
switch model), `/search`, `/image`, `/mcp`, `/memory`, `/remember`, `/reload`, `/help`,
and `/` (command menu). `/duo <goal>` selects Generator + Evaluator; `/triad <goal>`
selects Planner confirmation + Generator/Evaluator. Missing goals return bounded usage
guidance. Unknown
slash commands are rejected. Bare `models`, `reload`, `mcp`, and `mcp ...` are
ordinary model goals. The top-level `forgeagent models` CLI subcommand remains a
separate command and is not REPL routing.
