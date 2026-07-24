# audit-logging Specification

## Purpose
定义核心执行、HTTP 生命周期、Loop 与协作运行时的稳定、可关联、最小披露 JSONL 审计合同。
## Requirements
### Requirement: Core-layer audit events cover the execution boundary

The core execution path MUST emit audit events for every logical tool operation, every model request attempt/outcome, and every confirmation-gate decision, regardless of whether the task was started by CLI or HTTP. Retries and streaming attempts MUST be distinguishable without producing ambiguous duplicate logical-operation records.

#### Scenario: Tool execution event
- **WHEN** a tool is allowed, denied, or fails during a task
- **THEN** exactly one tool audit event records the operation type, task correlation, risk level, outcome, and duration

#### Scenario: LLM call event
- **WHEN** a model request succeeds, returns a structured client error, or is interrupted
- **THEN** one LLM audit event records the model group/identifier, safe outcome, token metadata available from the client, and duration without prompt secrets

#### Scenario: Confirmation decision event
- **WHEN** a gated tool is pre-authorized, interactively approved, or denied by the headless confirmer
- **THEN** one confirmation event records the decision, risk level, tool kind, task correlation, and safe parameter summary

### Requirement: Audit records have a stable, masked JSONL schema

Each audit line MUST be one valid JSON object containing an event timestamp, event type, task identifier when available, risk level, masked parameter summary, result status, elapsed duration, and an operation/attempt correlation when applicable; serialization MUST be append-only and parseable line by line.

#### Scenario: Complete event fields
- **WHEN** a core event is written
- **THEN** its JSON object contains the required fields with stable scalar/object types and an UTC timestamp

#### Scenario: Secret masking before persistence
- **WHEN** event parameters, model metadata, tool arguments, or errors contain known secret names or values
- **THEN** masking occurs before JSON serialization and the raw secret is absent from the resulting line

#### Scenario: Malformed event data
- **WHEN** an event field contains an unserializable value or unsafe control characters
- **THEN** the logger writes a safe fallback representation or a bounded logging error without crashing the task worker or exposing raw data

### Requirement: Audit retention is bounded and concurrent writes are safe

The audit logger MUST support configurable size-based rotation with a finite retention count, serialize concurrent writers so lines are not interleaved, and preserve valid JSONL across rotations.

#### Scenario: Rotation at size limit
- **WHEN** appending an event would exceed the configured byte limit
- **THEN** the current file is rotated before the append, old files beyond the retention count are removed, and the new event is written as a complete JSON line

#### Scenario: Concurrent event writes
- **WHEN** multiple task workers emit events concurrently
- **THEN** every accepted event is either present once in a valid JSONL file or reported through a bounded logger error, with no partial/interleaved JSON records

#### Scenario: Disabled or unavailable audit path
- **WHEN** audit logging is explicitly disabled or its path cannot be opened
- **THEN** task execution follows the documented fail-open/fail-closed configuration, and the service reports the condition without silently claiming that events were persisted

### Requirement: Audit output is minimally disclosing and operationally attributable

Audit records MUST identify the risk level and operation outcome needed for replay/diagnosis while omitting bearer tokens, API keys, full prompts, file contents, and host-absolute paths.

#### Scenario: HTTP request correlation
- **WHEN** a task is submitted, queried, or cancelled through HTTP
- **THEN** core audit events for that task carry the same task identifier and do not log the bearer token

#### Scenario: HTTP lifecycle rejection is audited
- **WHEN** HTTP authentication fails, a task is rejected for capacity, or a headless confirmation denies an operation
- **THEN** one masked lifecycle or confirmation event records the route/operation and safe result status without the token, raw request body, or sensitive arguments

#### Scenario: Audit write failure is visible but non-disclosing
- **WHEN** a runtime audit append fails after service startup
- **THEN** the task/service is marked audit-degraded, a fixed diagnostic is emitted, and no response or event claims that the failed record was persisted

#### Scenario: Restricted file or web operation
- **WHEN** a FileRead, FileWrite, or WebFetch operation is audited
- **THEN** the record contains only the existing sanitized project-relative/path or artifact summary and never raw content or an unmasked URL/host path

### Requirement: LLM outcome 记录 normalized cache hit rate
每个成功的 `llm.outcome` 审计事件 MUST 在保留既有原始 usage 计数的同时记录使用统一 total prompt denominator 计算的 `cache_hit_rate`。该指标 MUST 与 CLI 的计算语义一致，不得包含 prompt、工具参数、文件内容或其他新增敏感数据。

#### Scenario: 有可用分母的成功调用
- **WHEN** 一个成功 LLM 调用返回 cached tokens 和非零 normalized total prompt tokens
- **THEN** `llm.outcome.parameters.usage` 保留原始计数，且同级 `cache_hit_rate` 写入 0 到 1 范围内的数值

#### Scenario: 零分母或 provider 未报告 usage
- **WHEN** normalized total prompt token 分母为零或不可获得
- **THEN** `llm.outcome.parameters.cache_hit_rate` 写入 JSON `null`，审计序列化继续成功

#### Scenario: Provider 原始口径不同
- **WHEN** Anthropic 与 OpenAI-compatible 对等调用分别产生 usage
- **THEN** 两类事件使用各自 adapter 提供的 normalized denominator，而不是在审计层按模型名称猜测口径

#### Scenario: 审计写入降级
- **WHEN** 包含 cache hit rate 的审计事件写入失败
- **THEN** 任务执行继续遵循既有 fail-open 和 `audit_degraded` 语义，不因新增指标改变任务结果

### Requirement: Loop lifecycle events are attributable and minimally disclosing
The core Loop path MUST emit audit events for Loop start/resume, successful checkpoint persistence, iteration outcome, and terminal stop. Events MUST carry the Loop/task correlation and bounded counters while omitting the goal, checkpoint body, handoff text, completed/pending item text, absolute checkpoint path, prompts, credentials, and raw failure detail.

#### Scenario: Loop starts or resumes
- **WHEN** a CLI or HTTP request starts or resumes a Loop
- **THEN** one lifecycle event records the public trigger kind, Loop identifier, safe budget presence/limits, and `started` or `resumed` result without goal or checkpoint content

#### Scenario: Checkpoint persists
- **WHEN** a model checkpoint or automatic iteration checkpoint is atomically committed
- **THEN** one event records Loop/task correlation, schema version, iteration and aggregate item counts, and success without item text or host path

#### Scenario: Loop iteration ends
- **WHEN** an underlying Task iteration completes or fails
- **THEN** one event records the stable Task reason and cumulative round/token/failure counters without raw model response or failure text

#### Scenario: Loop reaches terminal state
- **WHEN** a Loop completes, is cancelled, reaches a budget, or encounters an unrecoverable checkpoint/configuration failure
- **THEN** one event records the stable terminal and stop reason plus bounded counters, and serialization failure follows the existing audit-degraded behavior

### Requirement: Collaboration lifecycle events are attributable and minimally disclosing
The collaboration path MUST emit audit events for mode routing, role start/outcome, plan submission/confirmation, evaluation verdict, rejection and terminal stop. Events MUST carry task/Loop correlation, stable mode/role/phase/model identifiers and bounded counters while omitting the goal, plan text, evaluation feedback text, prompts, tool arguments, artifact contents, credentials and absolute paths.

#### Scenario: Role lifecycle is audited
- **WHEN** Planner, Generator or Evaluator starts and reaches an outcome
- **THEN** events record role, mode, attempt, model identifier, stable status, duration and normalized usage without conversation content

#### Scenario: Plan confirmation is audited
- **WHEN** an interactive user or headless policy approves, denies or cannot confirm a Planner plan
- **THEN** one event records the decision, plan item count and digest prefix without plan text or goal

#### Scenario: Evaluation rejection is audited
- **WHEN** Evaluator rejects one or more acceptance items
- **THEN** one event records pass/fail counts, rejection number and bounded reason enums without actual/expected text or file contents

#### Scenario: Collaboration stops
- **WHEN** collaboration completes, exhausts rejection attempts, fails, needs confirmation or is cancelled
- **THEN** one event records mode, terminal reason and cumulative counters, and serialization failure follows existing audit-degraded behavior
