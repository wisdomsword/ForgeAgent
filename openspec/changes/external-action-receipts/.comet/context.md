# Comet Design Handoff

- Change: external-action-receipts
- Phase: design
- Mode: compact
- Context hash: 0c1651109076ccf861cd58e1403e134c1e266c2cb6f2be4feb6e602f16e95845

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/external-action-receipts/proposal.md

- Source: openspec/changes/external-action-receipts/proposal.md
- Lines: 1-33
- SHA256: 5bacb4dd830d4352c0812a7911ac4de48c3b7fbdc7c74d6566e47fd7eb66f756

```md
## Why

ForgeAgent 的 MCP 调用运行在宿主进程并可能产生真实外部副作用；当前调用在请求已发出但进程、网络或 facade 超时导致结果丢失时，只会返回普通失败，Loop 恢复后可能再次执行同一动作。M28 已明确把这类 replay 风险列为残余边界，因此下一阶段先建立可持久化、可审计、可人工 reconciliation 的最小收据协议。

## What Changes

- 新增项目内耐久外部动作收据，使用 `prepared`、`dispatched`、`confirmed`、`unknown` 四态记录动作身份、请求摘要、目标安全标签、任务/Loop 关联和结果证据。
- 对需要确认的 MCP 调用启用收据；现有 `autoApprove` 只读调用保持当前轻量路径，不纳入首期副作用收据。
- MCP 调用结果区分“未进入远端调用”“收到权威结果”和“可能已发出但结果未知”，不再把 facade 超时等不确定结果折叠为可安全重试的普通失败。
- 新增只读列举和显式 reconciliation 命令；用户可在外部核实后把未知动作标记为已确认、允许重试或放弃，系统不会自动替用户作出副作用决策。
- Loop 在启动下一次迭代或 resume 前检查同一 Loop 的未决收据；存在未决动作时以稳定停止原因返回，不调用模型、不调用工具、不静默重放。
- 收据迁移写入脱敏 audit 投影；audit 保持现有 fail-open 诊断角色，不作为阻止重放的权威状态。
- 更新威胁模型、CLI 文档和离线回归测试。
- 不改变 `FileWrite`、`Exec`、`Edit` 的现有语义，不实现通用补偿编排，不承诺远端 exactly-once。

## Capabilities

### New Capabilities

- `external-action-receipts`: 定义外部副作用动作的耐久收据、确定性状态迁移、未决动作阻断和人工 reconciliation 合同。

### Modified Capabilities

- `mcp-resilience`: MCP 调用需要向收据层报告未发出、已确认或结果未知的确定性，并让需要确认的调用接入收据协议。
- `loop-execution`: Loop 启动和恢复需要在执行下一迭代前检测未决外部动作并停止，禁止自动重放。
- `audit-logging`: 审计需要记录脱敏的外部动作收据状态迁移，同时保持与权威收据存储的职责分离。

## Impact

- 主要影响 `src/forgeagent/tools.py`、`src/forgeagent/mcp_manager.py`、`src/forgeagent/task.py`、`src/forgeagent/step.py`、`src/forgeagent/loop.py`、CLI/HTTP Task 装配和新增的收据存储模块。
- 增加项目根目录下 `.forgeagent` 内的私有、原子、版本化收据文件；不新增第三方依赖。
- 增加收据专项单测、MCP/Loop/CLI/Audit 回归，以及威胁模型和用户文档更新。
- `publish-v0-1-0` 保持独立暂停；本 change 不上传 PyPI、不创建或推送正式 tag。

```

## openspec/changes/external-action-receipts/design.md

- Source: openspec/changes/external-action-receipts/design.md
- Lines: 1-75
- SHA256: 5fdf66674a45dbf7f6dfa50446b283dabbb2e09e7440655735a1230431cda037

```md
## 背景

MCP 运行在宿主进程中，位于 restricted/container executor 之外，可能修改外部系统。当前 `MCPTool` 已有确认门，但 `MCPManager.call_tool()` 对超时或异常只返回有界的 `{"ok", "text"}`，会把“可能已经发出”的动作折叠成普通失败。`LoopCheckpointStore` 能保存 Loop 进度，却不能覆盖普通 Task；审计又明确采用 fail-open 语义。因此需要一个同时服务普通 Task 和 Loop Task 的独立权威收据存储。

## 目标 / 非目标

**目标：**

- 对获准的非只读 MCP 调用，在发出前持久化严格、脱敏的收据。
- 区分未发出、收到协议响应和结果未知，不向模型暴露 SDK 异常。
- 在 Loop resume 和下一次迭代前阻断未决收据。
- 提供有界列举和显式 reconciliation，禁止自动重放。
- 复用现有确认门、MCP 生命周期、audit、allowed-root 和原子写入约定。

**非目标：**

- 本阶段不为配置的只读 `autoApprove` MCP 调用创建收据。
- 不把 `FileWrite`、`Exec`、`Edit` 或 `WebFetch` 改造成收据事务。
- 不提供远端 exactly-once 保证、通用补偿引擎、分布式数据库或新依赖。
- `unknown` 后不自动重试；新尝试必须有新的动作标识和显式授权。

## 技术决策

### 1. 使用独立的权威收据存储

新增 `ExternalActionReceiptStore` 模块，在项目 allowed root 下的 `.forgeagent/receipts/` 保存每个动作的严格版本化 JSON 收据。存储沿用 Loop checkpoint 的安全模式：目录描述符绑定、符号链接检查、有界字段、每动作锁文件、临时文件原子替换和 `fsync`。对外提供 create、phase-transition、list-pending、load、reconcile 操作；audit 只接收投影。

**不采用的方案：** 将收据字段直接写入 JSONL audit 会继承 audit fail-open 语义，无法安全阻断重放；只扩展 LoopCheckpoint 会漏掉普通 Task，并把不相关的进度状态耦合到外部动作。

### 2. 四阶段与独立决策字段分离

权威 delivery phase 严格限定为 `prepared`、`dispatched`、`confirmed`、`unknown`。另设有界 resolution 字段（`open`、`confirmed`、`abandoned`、`retry_approved`）记录人工决策，不把人工决策混入 delivery phase。`unknown` 即使已经 resolution 也保留历史；任何重试都创建新的 receipt/action ID，并链接原收据。

**不采用的方案：** 用 `abandoned` 或 `retried` 作为 delivery phase 会混淆远端是否被联系过；将 delivery certainty 与人工 resolution 分离才能保持四态契约清晰。

### 3. 收据边界放在 `MCPTool`

保留现有确认门。非 auto-approved MCP 调用通过确认后，`MCPTool` 请求 manager 提供安全目标摘要，创建 `prepared` 收据；在 `MCPManager` 调用 SDK session 前立即标记 `dispatched`；再根据 manager 的内部 certainty 结果转为 `confirmed` 或 `unknown`。已自动批准的调用保持当前路径。

**不采用的方案：** 让每个 `Tool.run()` 都理解收据会扩大本里程碑，并错误地把本地文件动作当成远端不确定投递。

### 4. Manager 保持兼容的内部扩展

`MCPManager.call_tool()` 保留现有 `ok/text` 字段，在结果映射中增加内部 certainty 字段；`MCPTool` 消费该字段，并为 unknown 返回固定反馈。SDK 异常文本仍不得进入模型、CLI 或 audit。

### 5. Loop 在模型构造前执行 gate

`LoopRunner.resume()` 在返回可运行 runner 前检查 pending receipts；`LoopRunner.run()` 在每次迭代前再次检查，覆盖上一迭代刚产生收据的情况。发现未决收据时写入稳定的 `external_action_pending` 停止原因并返回现有安全报告投影，不创建 Task，不调用 collaboration builder。

**不采用的方案：** 只把警告注入下一轮 prompt 会允许模型忽略警告并重放，违反 fail-closed 恢复要求。

### 6. CLI reconciliation 显式且有界

增加 `receipts` CLI 子命令，提供 `list` 和 `resolve`。`list` 只展示脱敏的标识、phase、resolution、目标标签、时间戳以及 Task/Loop 关联。`resolve` 要求 `--confirmed`、`--abandon`、`--retry` 三者恰选其一；确认时必须提供有界 evidence。`--retry` 只授权未来调用逻辑，不执行原动作。

## 风险 / 取舍

- [收据存储不可用] → 拒绝受保护 MCP dispatch，返回固定错误；覆盖权限、符号链接替换、畸形记录和原子写失败测试。
- [持久化 transition 与 SDK 调用之间崩溃] → `prepared`/`dispatched` 作为未决状态阻断 resume；由 reconciliation 保守处理。
- [MCP 协议错误不等于业务结果] → 只有收到协议层响应才记录 `confirmed`，另行保存 server error 状态，不宣称业务成功。
- [旧调用方只读取 `ok/text`] → 保留这两个字段，仅增加内部可选 certainty，并添加兼容测试。
- [CLI/HTTP 并发 reconciliation] → 单收据加锁并拒绝 stale revision，不覆盖更新的 transition。
- [audit sink fail-open] → pending 判断永远不读取 audit；权威收据独立决定，audit 只按既有语义报告 degraded。

## 迁移计划

1. 先新增收据模型/存储和单测，不改变现有工具行为。
2. 增加 MCP 内部 certainty 结果，仅让非 auto-approved 调用接入收据。
3. 增加 Loop gate 与 CLI 列举/reconciliation，再更新 audit/威胁模型文档。
4. 既有项目没有收据文件，因此行为不变；新出现的畸形或不安全收据 fail closed。
5. 回滚时移除新集成路径，收据文件保留为不可执行的历史；回滚过程不自动重放外部动作。

## 开放问题

本里程碑没有阻塞性问题。支持 provider-specific 幂等键的远端系统可在后续 change 接入；本阶段只记录 request digest，不宣称 MCP server 实际遵守幂等语义。

```

## openspec/changes/external-action-receipts/tasks.md

- Source: openspec/changes/external-action-receipts/tasks.md
- Lines: 1-27
- SHA256: 3b354f4188faf99d2920f80efd2bf1f19e336c10f95c35d607d795b4e2af2af4

```md
## 1. 收据模型与耐久存储

- [ ] 1.1 增加严格收据模型、四种 delivery phase、独立 resolution 字段、有界脱敏/转义和稳定 schema 校验。
- [ ] 1.2 实现符号链接安全、allowed-root 约束、原子替换、每动作 revision 锁、list/load/pending 查询和畸形记录 fail-closed 的收据存储。
- [ ] 1.3 增加 create/transition/reconcile、中断后的中间状态、stale revision、畸形文件、路径替换、字段边界和 secret masking 的专项测试。

## 2. MCP dispatch 集成

- [ ] 2.1 扩展 MCP 内部结果，区分 `not_dispatched`、`confirmed`、`unknown`，保留现有 `ok/text` 和脱敏错误语义。
- [ ] 2.2 让非 auto-approved MCP 调用经过 prepared/dispatched/confirmed-or-unknown 收据迁移；保持现有确认门、HTTP allowlist 和只读自动批准路径。
- [ ] 2.3 返回固定 result-unknown 反馈，增加收据迁移 audit 投影，并测试拒绝、预批准、协议错误、超时/取消、不可用 session 和 audit degraded 路径。

## 3. Loop 与入口恢复 gate

- [ ] 3.1 在 Loop resume 和迭代前加入未决收据检查，使用稳定的 `external_action_pending` 停止语义；阻断时不得创建 Task 或模型调用。
- [ ] 3.2 在 CLI、HTTP 和 collaboration Task 装配中传递 receipt store、Task/Loop 关联，不改变无 MCP Task 行为。
- [ ] 3.3 增加 resume 阻断、下一迭代阻断、reconciliation 后继续、新动作 ID 和普通无收据 Loop 的确定性测试。

## 4. 显式 reconciliation 接口

- [ ] 4.1 增加有界的 `forgeagent receipts list` 和 `forgeagent receipts resolve` CLI 命令，要求互斥决策并校验证据。
- [ ] 4.2 增加列举、确认、放弃、重试授权、stale revision、脱敏和不自动 dispatch 的 CLI 测试。

## 5. 文档与验证

- [ ] 5.1 更新威胁模型、MCP/Loop 用户文档和与发布无关的能力说明，明确 unknown 状态和禁止重放契约。
- [ ] 5.2 执行专项测试、全量 pytest、Ruff、构建、OpenSpec strict 校验和两轮自评审；记录残余限制，不恢复 PyPI 发布。

```

## openspec/changes/external-action-receipts/specs/audit-logging/spec.md

- Source: openspec/changes/external-action-receipts/specs/audit-logging/spec.md
- Lines: 1-16
- SHA256: 55e0f6e2642dcf3208e5863abe611c3598d9891d343882b5a6209772e4d067b4

```md
## ADDED Requirements

### Requirement: External receipt transitions are audited as projections
ForgeAgent SHALL emit one bounded, masked audit event for each external receipt creation, dispatch transition, confirmation, unknown result, or reconciliation decision. Audit records MUST reference the receipt/action identifier and stable status while omitting raw MCP arguments, credentials, full evidence text, and host paths. Audit failure MUST NOT make an unrecorded external dispatch appear safe to replay; the receipt store remains authoritative.

#### Scenario: Receipt transition is audited
- **WHEN** a receipt changes phase or receives a reconciliation decision
- **THEN** exactly one audit event records the action correlation, stable phase/decision, and safe target summary

#### Scenario: Audit sink is unavailable
- **WHEN** the audit sink rejects a receipt event
- **THEN** the authoritative receipt transition remains the source of truth, the audit sink is marked degraded using existing behavior, and no public response claims that the audit event was persisted

#### Scenario: Receipt audit data contains sensitive values
- **WHEN** a receipt target or evidence reference contains known secrets or unsafe control characters
- **THEN** the emitted audit JSONL contains masked, escaped, bounded values and no raw sensitive material

```

## openspec/changes/external-action-receipts/specs/external-action-receipts/spec.md

- Source: openspec/changes/external-action-receipts/specs/external-action-receipts/spec.md
- Lines: 1-57
- SHA256: 96e6defb9a94724a99de84827f9a86749abf1243110afdf96488bf105d96550e

```md
## ADDED Requirements

### Requirement: External action receipts are durable and strictly bounded
ForgeAgent SHALL persist one versioned receipt for every approved, non-read-only external action before dispatch. The receipt MUST use the phases `prepared`, `dispatched`, `confirmed`, and `unknown`, MUST preserve a stable action identifier and request digest, and MUST store only bounded, secret-masked target metadata and evidence references. Receipt writes and phase transitions MUST be atomic and fail closed when the authoritative receipt cannot be persisted.

#### Scenario: Approved action is prepared before dispatch
- **WHEN** a user or server-owned policy approves a non-read-only MCP action
- **THEN** ForgeAgent durably writes a `prepared` receipt before invoking the external MCP session

#### Scenario: Receipt persistence is unavailable
- **WHEN** ForgeAgent cannot safely create or atomically update the receipt store
- **THEN** ForgeAgent does not dispatch the external action and returns a fixed receipt-unavailable failure

#### Scenario: Receipt metadata contains secrets or oversized text
- **WHEN** target labels, argument summaries, evidence references, or error text contain known secrets, control characters, or exceed configured bounds
- **THEN** the persisted receipt contains only masked, escaped, bounded values and never the raw material

### Requirement: Receipt transitions distinguish dispatch certainty
ForgeAgent SHALL transition a receipt to `dispatched` before the external call, to `confirmed` only after receiving an authoritative MCP protocol response or authoritative no-dispatch result, and to `unknown` when dispatch may have occurred but no authoritative result is available. ForgeAgent MUST NOT treat `unknown` as an ordinary retryable failure.

#### Scenario: External call returns an MCP response
- **WHEN** a dispatched MCP action receives a protocol response, including a server-declared error response
- **THEN** ForgeAgent records `confirmed` with a bounded evidence reference and returns the existing structured tool outcome semantics

#### Scenario: External call times out after dispatch
- **WHEN** the MCP session call times out, is cancelled, or raises after the receipt is `dispatched`
- **THEN** ForgeAgent records `unknown`, returns a fixed result-unknown outcome, and does not claim the external action failed before dispatch

#### Scenario: MCP server is unavailable before dispatch
- **WHEN** ForgeAgent can prove that no MCP session call was started
- **THEN** ForgeAgent records an authoritative no-dispatch result and does not expose the action as an unresolved external side effect

### Requirement: Reconciliation is explicit and never silently replays
ForgeAgent SHALL provide a bounded read-only receipt listing and an explicit reconciliation operation for unresolved receipts. Reconciliation MUST require a user or server-owned caller to choose confirmation with evidence, abandonment, or permission for a new attempt; ForgeAgent MUST never issue the original external action automatically as part of listing, resume, retry, or process startup.

#### Scenario: List unresolved receipts
- **WHEN** a user lists receipts for a project or Loop
- **THEN** ForgeAgent returns only bounded, masked metadata and identifies receipts whose phase is `prepared`, `dispatched`, or `unknown` without reading or exposing raw arguments

#### Scenario: Confirm an unknown action
- **WHEN** a user resolves an `unknown` receipt as confirmed and supplies bounded evidence
- **THEN** ForgeAgent records the evidence, marks the receipt resolved, emits an audit event, and does not dispatch any action

#### Scenario: Abandon or approve a new attempt
- **WHEN** a user resolves an unresolved receipt as abandoned or explicitly permits a new attempt
- **THEN** ForgeAgent records the decision, keeps the original receipt immutable as history, and requires any new attempt to receive a new action identifier

### Requirement: Receipt storage is scoped and recoverable
Receipt records SHALL be scoped to the canonical allowed project root and MAY carry a task and Loop correlation. Loading MUST reject unsafe paths, malformed records, unknown schema versions, extra fields, and oversized content. A partial or corrupt latest record MUST fail closed for that action rather than silently deleting history.

#### Scenario: Load receipts after process restart
- **WHEN** ForgeAgent starts or resumes after a process interruption
- **THEN** it can enumerate valid receipts from the same allowed root and preserve their phases and reconciliation decisions

#### Scenario: Receipt file is replaced or malformed
- **WHEN** a receipt path is a symlink, outside the allowed root, malformed, or contains an unknown schema
- **THEN** ForgeAgent rejects the record, reports a fixed receipt-store error, and does not dispatch related actions

```

## openspec/changes/external-action-receipts/specs/loop-execution/spec.md

- Source: openspec/changes/external-action-receipts/specs/loop-execution/spec.md
- Lines: 1-16
- SHA256: 717a322148e07af2f3c7cf201a38faa67010a45f8e4624843555d439a4aa82fa

```md
## ADDED Requirements

### Requirement: Loop execution gates on unresolved external actions
Before starting a new Loop iteration and before executing a resumed Loop, ForgeAgent MUST query the authoritative receipt store for unresolved receipts belonging to that Loop. If any receipt is unresolved, the Loop MUST stop with a stable `external_action_pending` reason and MUST NOT invoke a model, tool, collaboration role, or automatic retry.

#### Scenario: Resume with an unresolved receipt
- **WHEN** a valid Loop checkpoint is resumed while one of its receipts is `prepared`, `dispatched`, or `unknown` without reconciliation
- **THEN** ForgeAgent returns a bounded stopped report with `external_action_pending` before creating a Task

#### Scenario: Iteration leaves an unresolved receipt
- **WHEN** a running Loop iteration produces an unresolved external action
- **THEN** the Loop persists its normal accounting, then stops at the next safe boundary with `external_action_pending` and does not start another iteration

#### Scenario: Reconciled receipt permits continuation
- **WHEN** all receipts for a Loop are confirmed, abandoned, or explicitly resolved for a new attempt
- **THEN** Loop resume may continue, but no original action is replayed automatically and any new action uses a new identifier

```

## openspec/changes/external-action-receipts/specs/mcp-resilience/spec.md

- Source: openspec/changes/external-action-receipts/specs/mcp-resilience/spec.md
- Lines: 1-31
- SHA256: 74ac84154b016a21040b31283d6ff8c1ee0a80f8175bdfdab9876ad22a7ee457

```md
## ADDED Requirements

### Requirement: Non-read-only MCP calls use external action receipts
ForgeAgent SHALL classify MCP calls that are not covered by the configured read-only `autoApprove` allowlist as receipt-protected actions. The existing confirmation and HTTP headless allowlist gates MUST run before receipt creation, and denied calls MUST NOT create a dispatchable receipt.

#### Scenario: Read-only auto-approved MCP call
- **WHEN** a CLI or REPL MCP call matches the configured `autoApprove` entry
- **THEN** ForgeAgent preserves the existing direct call path and does not create an external action receipt

#### Scenario: Approved side-effecting MCP call
- **WHEN** a non-auto-approved MCP call passes the existing confirmer or HTTP headless allowlist
- **THEN** ForgeAgent creates and advances a receipt around the MCP dispatch

#### Scenario: Side-effecting MCP call is denied
- **WHEN** the existing confirmer or HTTP headless allowlist rejects a non-auto-approved MCP call
- **THEN** ForgeAgent returns the existing structured rejection and creates no prepared, dispatched, or unknown receipt

### Requirement: MCP call results expose dispatch certainty
The MCP manager SHALL return an internal dispatch-certainty classification that distinguishes `not_dispatched`, `confirmed`, and `unknown` without exposing raw SDK exceptions. The public ToolOutcome MUST remain bounded and MUST identify result-unknown cases so the caller can reconcile them rather than retrying automatically.

#### Scenario: MCP call has no live session
- **WHEN** the manager rejects the call before invoking the SDK session
- **THEN** the internal result is `not_dispatched` and the ToolOutcome remains a fixed unavailable failure

#### Scenario: MCP call receives a response
- **WHEN** the SDK session returns a normal MCP result object
- **THEN** the internal result is `confirmed`, regardless of the server's `isError` flag, and the receipt records protocol-response evidence

#### Scenario: MCP call loses certainty
- **WHEN** the SDK call raises, times out, or is cancelled after dispatch
- **THEN** the internal result is `unknown`, the ToolOutcome uses fixed result-unknown text, and the manager does not invalidate the receipt as a normal retryable failure

```
