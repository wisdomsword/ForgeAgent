# Comet Design Handoff

- Change: attention-state-projection
- Phase: design
- Mode: compact
- Context hash: 9fab4800470e9af84371912bb1ee97fdd4420001dd5098718bd5ee926a059a4c

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/attention-state-projection/proposal.md

- Source: openspec/changes/attention-state-projection/proposal.md
- Lines: 1-30
- SHA256: 8aa548edf2cd0e9f5864fe189e4f1e9611b4916d2bbeb604e3d437535371b37b

```md
## Why

ForgeAgent 已能区分普通终态，但仍会把“等待用户或外部资源”的任务与失败任务混在一起。当前 `Survey` 只暴露 `needs_info`，Loop 和 HTTP 调用方没有稳定的 attention-state 契约，导致 headless 客户端无法判断应当补充输入、解除阻塞、重试还是按终态处理。

## What Changes

- 增加最小 attention-state 协议，将终态结果与可行动的注意力状态分离。
- 保留 `needs_info` 作为兼容输入，并映射为新的 `needs_input` attention state。
- 为 Loop 增加稳定的 `needs_input`、`blocked` stop reason，以及有界的 reason/detail/recovery 元数据。
- 通过 HTTP 任务提交和查询响应投影 attention state，但不暴露 prompt、工具参数或宿主数据。
- 保持取消、完成、失败和 `external_action_pending` 的既有语义不变。
- 增加确定性的单测、HTTP、Loop 和兼容性回归覆盖。

## Capabilities

### New Capabilities

- `attention-state-protocol`: Stable attention-state vocabulary, metadata, compatibility mapping, and public projection rules.

### Modified Capabilities

- `loop-execution`: Allow Loop reports to stop with `needs_input` or `blocked` and carry bounded attention metadata.
- `http-task-service`: Project attention state and recovery metadata for queued/running/terminal task views while preserving existing safe disclosure rules.

## Impact

- 运行时模块：按需修改 `src/forgeagent/step.py`、`src/forgeagent/task.py`、`src/forgeagent/loop.py`、`src/forgeagent/http_task_service.py` 和 `src/forgeagent/http_server.py`。
- 公共 JSON：新增 `attention` 对象和稳定的公开状态值；原有 `status`、`reason`、`detail` 字段继续保留。
- 不新增依赖、数据库、调度器、鉴权模式或发布动作。
- PyPI 发布、正式 tag、远程 push，以及 active 的 `publish-v0-1-0` change 均不在范围内并继续暂停。

```

## openspec/changes/attention-state-projection/design.md

- Source: openspec/changes/attention-state-projection/design.md
- Lines: 1-21
- SHA256: b5cbd18292414633b0d8ec1f72e31c8f61bb33622ef68f89cb6b3e7a6b9dbb70

```md
## 目标

在现有 `Termination.NEEDS_INFO`、Loop checkpoint 和 HTTP `TaskRecord.public_view()` 之上增加最小注意力协议，解决“需要输入/被阻塞”被误读为失败的问题，同时保持旧字段和发布暂停不变。

## 方案

1. 在 `step.py`/`task.py` 中保留旧 `needs_info` 终态，新增内部 attention projection helper，统一生成 `state`、`reason`、`owner`、`required_action`、`recovery` 五个有界字段。
2. 在 Loop 中增加 `needs_input`、`blocked` stop reason，允许 `status=stopped`，并把 attention metadata 持久化到 checkpoint/report；现有 `external_action_pending` 继续表示外部动作未决，不改名、不自动映射为 blocked。
3. 在 HTTP TaskRecord 中按普通 Task、Loop、Duo/Triad 结果投影 `attention` 对象：queued/running 为 `running`，`needs_info` 为 `needs_input`，`external_action_pending` 与明确阻塞为 `blocked`，成功/可消费结果为 `ready`。
4. 所有公开文本复用已有掩码和长度限制；状态转换复用 AuditEvent，失败沿用 audit_degraded。

## 取舍与边界

- 不将注意力状态改造成新的终态枚举；终态仍由 `status`/`reason` 表示，避免破坏 M28 RC 合同。
- 不实现服务器端等待队列、自动恢复、通知、调度器或新的确认机制；调用方负责提供输入或解除阻塞后显式重新提交/恢复。
- 不新增依赖，不改变外部副作用收据协议；未决收据仍优先报告 `external_action_pending`。

## 验证

- 先写状态映射和边界失败测试，再实现；覆盖旧 `needs_info`、新 Loop stop reason、HTTP queued/running/needs-input/blocked/ready 投影、掩码/截断和审计降级。
- 运行专项测试、完整 pytest、Ruff、格式检查、build 与 OpenSpec strict 验证；发布相关任务不执行。

```

## openspec/changes/attention-state-projection/tasks.md

- Source: openspec/changes/attention-state-projection/tasks.md
- Lines: 1-19
- SHA256: 9b76c48f4b66e1be1aa65830bc8bd4d7a8e4ded6fb4f6ef68db90fcd467e17b0

```md
## 1. 注意力协议

- [ ] 1.1 增加有界 attention-state 类型/辅助函数和旧 `needs_info` 映射，并添加单测。
- [ ] 1.2 增加状态转换审计事件，以及安全掩码/截断测试。

## 2. Loop 接入

- [ ] 2.1 扩展 Loop 的 stop-reason/status 不变量，支持 `needs_input`、`blocked`，持久化有界元数据，并覆盖 checkpoint/report/resume 行为。
- [ ] 2.2 映射 Survey/模型的 attention 结果，不改变普通完成、取消或 `external_action_pending` 语义。

## 3. HTTP 投影

- [ ] 3.1 为普通 Task、Loop、Duo、Triad 记录的 TaskService snapshot 增加附加式 `attention` 投影。
- [ ] 3.2 增加 HTTP 生命周期测试，覆盖 running、needs-input、blocked、ready、旧版兼容和安全披露。

## 4. 文档与验证

- [ ] 4.1 更新 HTTP/Loop/threat-model 文档及 attention-state 语义的验证证据。
- [ ] 4.2 运行专项测试、完整 pytest、Ruff、build、OpenSpec strict 和最终两轮一致性评审；保持 PyPI 发布暂停。

```

## openspec/changes/attention-state-projection/specs/attention-state-protocol/spec.md

- Source: openspec/changes/attention-state-projection/specs/attention-state-protocol/spec.md
- Lines: 1-49
- SHA256: ef5deaa01f34e3800bb8bae4742eab272a1f43378043e4b3655221a862a5e4e7

```md
## ADDED Requirements

### Requirement: Attention state is separate from terminal outcome
ForgeAgent SHALL represent actionable attention independently from terminal execution outcome. The attention vocabulary MUST include `running`, `needs_input`, `blocked`, and `ready`; terminal outcomes MUST remain `succeeded`, `failed`, or `cancelled` (with existing public reason values preserved). A task MAY be `needs_input` or `blocked` without being a failed terminal outcome.

#### Scenario: Waiting for user input
- **WHEN** a Survey has no asker or a model declares `need_info`
- **THEN** the task exposes `attention.state=needs_input`, a bounded reason, the responsible party, and a recovery condition without classifying the task as an internal failure

#### Scenario: Waiting for an external dependency
- **WHEN** execution cannot continue because a permission, resource, or unresolved external action requires an explicit decision
- **THEN** the task exposes `attention.state=blocked` with a bounded reason and recovery condition, and does not silently retry

#### Scenario: Work is actionable after a non-terminal event
- **WHEN** a task has a result or checkpoint that can be consumed by the caller for its next action
- **THEN** the task exposes `attention.state=ready` even if the underlying Loop is not reported as succeeded

### Requirement: Attention metadata is bounded and safe
Every `needs_input` or `blocked` state MUST include a stable reason code, responsible party, required action or input, and recovery condition. Each field MUST be length-bounded, secret-masked, and free of full prompts, raw tool arguments, file contents, absolute host paths, and credentials. Missing optional metadata MUST use safe defaults rather than null ambiguity.

#### Scenario: Oversized or sensitive detail
- **WHEN** a model, tool, or worker supplies oversized detail or a value containing a configured secret
- **THEN** the public attention projection truncates and masks it before returning or auditing it

#### Scenario: Stable machine consumption
- **WHEN** an HTTP client receives an attention projection
- **THEN** the client can branch on stable `state` and `reason` fields without parsing prose

### Requirement: Legacy needs_info remains compatible
Existing `Termination.NEEDS_INFO`, `TaskStatus.reason=needs_info`, and `ToolOutcome.needs_info` inputs MUST remain readable. They MUST map to `attention.state=needs_input` with reason `user_input_required`, and existing CLI/HTTP reason fields MUST remain present for one compatibility period.

#### Scenario: Legacy Survey result
- **WHEN** a headless Survey returns the existing `needs_info=True` outcome
- **THEN** Step and Task preserve the `needs_info` reason while adding the equivalent `needs_input` attention projection

#### Scenario: Legacy serialized result
- **WHEN** a caller loads an existing result containing only `needs_info`
- **THEN** deserialization succeeds and derives the new attention state without rewriting historical data

### Requirement: Attention transitions are audited
Changes into or out of `needs_input`, `blocked`, and `ready` MUST emit a bounded audit event correlated to the task and Loop when available. Audit failure MUST set the existing degraded indicator and MUST NOT expose sensitive metadata.

#### Scenario: State transition
- **WHEN** a task enters or leaves an attention state
- **THEN** one correlated transition event records the stable state and reason code with masked bounded metadata

#### Scenario: Audit sink failure
- **WHEN** persisting an attention transition event fails
- **THEN** the task remains safe and the public projection marks audit degradation according to existing HTTP/CLI semantics

```

## openspec/changes/attention-state-projection/specs/http-task-service/spec.md

- Source: openspec/changes/attention-state-projection/specs/http-task-service/spec.md
- Lines: 1-29
- SHA256: 83c969c837b97797b9922f16a4ff12e71e45de247688b3687b133638ed05a462

```md
## MODIFIED Requirements

### Requirement: Task status and result retrieval

The service MUST expose authenticated queries for a task's lifecycle state and terminal result using the existing `TaskOutcome` semantics for ordinary tasks and a bounded Loop report projection for Loop tasks. It MUST NOT expose internal exceptions, secrets, full prompts, raw tool arguments, checkpoint contents, file contents, absolute host paths, or unbounded round history. Every response MUST include an additive bounded `attention` projection with stable `state` and `reason` fields; legacy `status`, `reason`, and `detail` fields MUST remain present.

#### Scenario: Running task query
- **WHEN** an authenticated client queries an ordinary task or Loop that has been accepted but is still running
- **THEN** the response identifies it as running, identifies the public execution mode, sets `attention.state=running`, and does not fabricate a terminal result

#### Scenario: Needs-input task query
- **WHEN** an authenticated client queries a task that stopped because a user answer or explicit confirmation is required
- **THEN** the response sets `attention.state=needs_input`, exposes bounded reason and recovery metadata, and retains the legacy `needs_info` reason when that is the underlying result

#### Scenario: Blocked task query
- **WHEN** an authenticated client queries a task that cannot continue until a permission, resource, or external action is resolved
- **THEN** the response sets `attention.state=blocked`, exposes the bounded recovery condition, and does not classify the task as `internal_error`

#### Scenario: Terminal task query
- **WHEN** an authenticated client queries a completed, stopped, failed, refused, needs-information, or cancelled task
- **THEN** the response includes the stable terminal status, reason, safe detail, mode, attention projection, and available bounded result data

#### Scenario: Unknown task query
- **WHEN** an authenticated client queries an identifier that is not retained by the service
- **THEN** the service returns a not-found error without revealing other task or Loop identifiers or stored content

#### Scenario: Safe result projection
- **WHEN** an authenticated client queries a terminal task whose rounds or checkpoint contain prompts, tool arguments, file contents, absolute paths, or handoff text
- **THEN** the response returns only bounded status/reason/detail/attention/mode/round-count/usage/Loop-counter fields with masking and truncation

```

## openspec/changes/attention-state-projection/specs/loop-execution/spec.md

- Source: openspec/changes/attention-state-projection/specs/loop-execution/spec.md
- Lines: 1-20
- SHA256: 0a6c0c150ec389bfdd23a267eef686c5726c3234e7e29fc3ac86a7811b338b93

```md
## MODIFIED Requirements

### Requirement: Loop 终态报告稳定、有界且可离线验证
每个 Loop MUST 产生包含 schema、Loop ID、终态、停止原因、迭代/轮次/token/墙钟计数、连续失败数和 checkpoint 摘要计数的稳定报告。公开 CLI/HTTP 投影 MUST 脱敏、限制长度且不得暴露完整 prompt、checkpoint 正文、tool 参数、文件内容、绝对宿主路径或 secret。Loop 报告 MAY additionally expose a bounded attention projection when its stop reason is `needs_input` or `blocked`; the attention projection MUST follow the attention-state-protocol contract and MUST NOT change the existing terminal status taxonomy.

#### Scenario: 成功完成报告
- **WHEN** 某次 Task 以严格 completed 终态结束
- **THEN** Loop 原子写入 completed 报告并返回累计预算与进度计数，且 attention state 为 `ready`

#### Scenario: 预算停止报告
- **WHEN** 任一停止预算命中
- **THEN** 报告使用稳定枚举标识首个生效停止原因，并保留不超过上限的安全诊断，且不得伪装为 `needs_input` 或 `blocked`

#### Scenario: Attention stop report
- **WHEN** Loop 因需要用户输入或外部阻塞在安全边界停止
- **THEN** 报告使用 `status=stopped`、稳定 `stop_reason`（`needs_input` 或 `blocked`）和 bounded attention metadata，resume 不得静默重放动作

#### Scenario: 离线端到端恢复验证
- **WHEN** 测试使用 MockClient 在 checkpoint 后模拟中断并恢复
- **THEN** 恢复执行不重做已完成条目，每种停止条件及 attention stop 均可由确定性断言验证且无需 API key

```
