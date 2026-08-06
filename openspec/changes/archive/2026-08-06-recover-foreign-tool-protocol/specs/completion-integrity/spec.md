## MODIFIED Requirements

### Requirement: Direct prose answers terminate without protocol recovery
In a single-role task without a required completion tool, ForgeAgent SHALL terminate a non-empty response that has no tool calls, no protocol parse errors, no unsupported external-agent tool syntax and no explicit terminal status as `answered_in_prose` in that same round. ForgeAgent MUST preserve this as an unverified soft completion and MUST NOT report it as execution-verified `completed`. ForgeAgent MUST treat an observed standalone `cmd` JSON envelope or `todo_write` + `Params:` envelope outside a Markdown code fence as a recoverable protocol error, MUST NOT execute it, and SHALL direct the model to the registered ForgeAgent ToolCall protocol.

#### Scenario: Informational answer completes in one round
- **WHEN** a model returns a non-empty plain-text answer with no tool calls, parse errors, unsupported external-agent tool syntax or explicit terminal status
- **THEN** ForgeAgent makes no recovery model call and terminates that round as `answered_in_prose`

#### Scenario: Streamed informational answer is displayed once
- **WHEN** a terminal streams a direct plain-text answer before rendering its final task outcome
- **THEN** ForgeAgent retains one copy of the answer and does not print the same round body again

#### Scenario: Required completion tool still takes precedence
- **WHEN** a role configured with a required completion tool returns plain text without successfully calling that tool
- **THEN** ForgeAgent does not accept the prose as a soft completion and applies the existing bounded submission recovery behavior

#### Scenario: Tool or parse feedback still continues
- **WHEN** a response contains tool activity, protocol parse errors or unsupported external-agent tool syntax
- **THEN** ForgeAgent processes and feeds back those results instead of terminating that response as `answered_in_prose`

#### Scenario: Standalone cmd envelope is not executed as prose
- **WHEN** a model emits a standalone JSON object with a string `cmd` field outside a Markdown code fence
- **THEN** ForgeAgent does not execute the command, reports a recoverable protocol error and asks the model to use ForgeAgent CodeBlock and Exec ToolCall syntax

#### Scenario: Todo envelope is not accepted as prose
- **WHEN** a model emits a `todo_write` tool name followed by a `Params:` payload outside a Markdown code fence
- **THEN** ForgeAgent reports a recoverable protocol error and keeps the same Task active

#### Scenario: Fenced protocol example remains prose
- **WHEN** an informational answer shows an external command envelope only inside a Markdown fenced code example
- **THEN** ForgeAgent does not classify that example as an attempted tool call and preserves direct prose completion
