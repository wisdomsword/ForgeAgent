# Text Protocol Specification

ForgeAgent uses Markdown plus HTML-comment markers so the task loop is independent of a provider's native function-calling API. OpenAI-compatible native tool calls are normalized into the same internal `ToolCall` form; the text protocol remains the portable contract.

## Markers

Code blocks use matching variable-length backtick fences and `CodeBlockStart`/`CodeBlockEnd` comments. Tool calls use one JSON comment:

```markdown
<!-- ToolCall: {"id":"call-1","name":"FileRead","arguments":{"path":"input.txt"}} -->
```

Unknown tool names, malformed JSON, missing fields, invalid schemas, and malformed task-status front matter produce structured parse errors. They are feedback to the model, not silent drops or parser crashes.

The active registry is the source of truth for recognized names and argument schemas. Built-ins are `Exec`, `Edit`, `Survey`, `WebFetch`, `FileRead`, `FileWrite`, and `FileList`; `MCP` is registered only when an MCP manager is present. Runtime `SubTask` is not part of this protocol.

## Tool arguments

| Tool | Required arguments | Contract |
| --- | --- | --- |
| `Exec` | `name` or `code` | Python only; `language` defaults to `python`. |
| `Edit` | `name`, `old`, `new` | Updates a named code block; `replace_all` defaults to false. |
| `Survey` | `question` | Optional `options`; without an asker it terminates as `need_info`. |
| `WebFetch` | `url` | GET-only HTTP(S) fetch. No arbitrary method or headers. |
| `FileRead` | `path` | Reads a path within `allowed_root`. |
| `FileWrite` | `path`, `content` | Creates or overwrites a path within `allowed_root`. |
| `FileList` | none | Lists direct entries under `path`, which defaults to `.`. |
| `MCP` | `server`, `tool` | Optional `arguments` mapping defaults to `{}`; the selected MCP tool validates its own argument schema. |

`WebFetch`/`File*` outcomes deliberately use fixed failure text where disclosure could expose a URL, host, absolute host path, or underlying exception. The tool result is still fed back to the model for repair.

## Completion is two-stage

The leading YAML front matter may declare:

```yaml
---
task_status:
  completed: true
  confidence: 0.9
---
```

Completion is strict:

1. A response containing any tool call or any parse error cannot complete, even when it also declares `completed: true`.
2. ForgeAgent executes the calls, records successful or failed outcomes, renders all outcomes and parse errors as feedback, and starts another model round.
3. Only a later, independent response with no tool calls, no parse errors, and `completed: true` becomes `completed`.

This rule applies equally to successful and failed tools. A same-round completion declaration was generated before the model saw tool results, so it is ignored. Declared non-completion statuses (`refused`, `need_info`, `failed`) retain their existing terminal meanings.

## Confirmation and terminal behavior

The protocol does not encode approval policy. The runtime applies tool-specific confirmation: WebFetch and FileWrite are gated in `restricted`/`container`; MCP calls are gated unless the selected server/tool is listed in `autoApprove`. In non-TTY operation, no confirmation input is read and a required confirmation is rejected. `--interactive` controls Survey only.

REPL commands require a slash prefix. Bare `models`, `reload`, `mcp`, and `mcp ...` are ordinary model goals. The top-level `forgeagent models` command remains a CLI subcommand and is unrelated to REPL routing.
