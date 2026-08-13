# completion-integrity Specification

## Purpose
Define evidence requirements that prevent prose, malformed submissions, or unverified tool outcomes from being accepted as task completion.
## Requirements
### Requirement: Tool-bearing responses cannot complete a task
ForgeAgent MUST apply the two-stage eligibility check only to an explicit `completed: true` declaration: it MUST ignore that completion declaration in any response that also contains one or more tool calls and SHALL feed the tool results into a later round.

#### Scenario: Successful tool and completion declaration share a response
- **WHEN** a model response declares `completed: true` and invokes a tool that succeeds
- **THEN** ForgeAgent records the tool result, continues to another model round and does not mark the task complete from that response

#### Scenario: Failed tool and completion declaration share a response
- **WHEN** a model response declares `completed: true` and invokes a tool that fails
- **THEN** ForgeAgent records the failure, continues to another model round and does not mark the task complete

### Requirement: Parse errors prevent same-round completion
ForgeAgent MUST NOT complete a task from a response that contains protocol parse errors, even when that response also declares completion.

#### Scenario: Completion declaration accompanies a parse error
- **WHEN** a model response contains a parse error and `completed: true`
- **THEN** ForgeAgent feeds the parse error back for correction and keeps the task incomplete

### Requirement: Completion requires a standalone final response
ForgeAgent SHALL mark a single-role task complete only from a response that explicitly declares completion, contains neither tool calls nor protocol parse errors, and has a non-empty body after protocol whitespace normalization. In Duo/Triad mode, the same standalone Generator response SHALL mean only "submitted for evaluation"; ForgeAgent MUST mark the collaborative execution complete only after an independent Evaluator returns a valid structured pass for every frozen acceptance item.

#### Scenario: Standalone completion after tool feedback
- **WHEN** a tool-bearing response has been processed and a later response contains no tools, no parse errors, a non-empty body and declares `completed: true` in single mode
- **THEN** ForgeAgent marks the task complete using the later response

#### Scenario: Empty standalone response does not complete
- **WHEN** a response declares `completed: true` but its body is empty or whitespace-only
- **THEN** ForgeAgent keeps the task incomplete and emits the existing empty-response correction feedback

#### Scenario: Collaborative Generator submits for evaluation
- **WHEN** a Duo/Triad Generator produces an otherwise eligible standalone `completed: true` response with a non-empty body
- **THEN** ForgeAgent starts an isolated Evaluator and does not yet report the collaborative execution as completed

#### Scenario: Evaluator rejects submitted work
- **WHEN** the independent Evaluator reports one or more frozen acceptance items as failed
- **THEN** ForgeAgent keeps the collaborative execution incomplete and either starts a bounded correction attempt or stops with a rejection report

### Requirement: Explicit non-completion keeps existing terminal semantics
An explicit `completed: false` declaration SHALL NOT be delayed, overwritten or reclassified by the two-stage completion eligibility check.

#### Scenario: Refused non-completion accompanies tool activity
- **WHEN** a response declares `completed: false` with status `refused` and also contains tool calls or parse errors
- **THEN** ForgeAgent preserves the existing `refused` terminal mapping rather than treating it as a blocked completion declaration

#### Scenario: Need-info or failed non-completion accompanies tool activity
- **WHEN** a response declares `completed: false` with status `need_info` or `failed` and also contains tool calls or parse errors
- **THEN** ForgeAgent preserves the existing corresponding terminal mapping rather than delaying it to a later round

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

### Requirement: 任务终态公开一致的完成语义
ForgeAgent MUST 把任务终态归类为 `verified_completed`、`answered_unverified` 或 `stopped`，并 MUST 仅在 `verified_completed` 时把兼容布尔 `completed` 投影为 true。

终态投影 MUST 由 `reason` 唯一派生，且已构造的 TaskStatus 不得允许调用方再单独修改 `completed` 或 `completion_state` 造成矛盾。

#### Scenario: prose 回答不得显示为已验证完成
- **WHEN** 模型给出非空 prose 回答但没有执行工具或程序
- **THEN** Task、CLI、HTTP 与 audit 都把该终态标为 `answered_unverified`，CLI 不得显示 `completed`，兼容布尔 `completed` 为 false

#### Scenario: 已验证完成保持兼容
- **WHEN** 任务按协议声明并达到 verified completion
- **THEN** 三态为 `verified_completed`，兼容布尔 `completed` 为 true，既有 verified-only 消费方行为不变

#### Scenario: 矛盾状态被拒绝
- **WHEN** 调用方同时提供互相矛盾的完成三态、布尔投影或终止原因
- **THEN** ForgeAgent 在状态构造时拒绝该输入，而不是序列化相互冲突的结果

#### Scenario: 终态投影不可漂移
- **WHEN** 调用方以既有布尔字段或仅以终态原因构造 TaskStatus
- **THEN** 系统 MUST 产生匹配原因的三态和兼容布尔投影
- **AND THEN** 构造后的状态不得允许单独改写其中任一字段
