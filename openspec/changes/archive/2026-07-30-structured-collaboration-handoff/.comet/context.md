# Comet Design Handoff

- Change: structured-collaboration-handoff
- Phase: design
- Mode: compact
- Context hash: 23adf759e91b048a01e8ddcf269ab026fcb4cfa987da19f3f52e3747203f9a17

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/structured-collaboration-handoff/proposal.md

- Source: openspec/changes/structured-collaboration-handoff/proposal.md
- Lines: 1-30
- SHA256: a830336794928d076818b87d9a097b7ca189d6aa82738fe4d4fa0f00179d5926

```md
# 结构化协作交接

## Why

现有 Duo/Triad 已耐久保存目标、冻结计划、评审结果、attempt、revision 和停止原因，但角色之间主要通过渲染后的 JSON task data 交接。目标范围、事实、假设、未决副作用、能力/审批和返回责任没有一个统一、可审计的契约；恢复时容易把“当前状态”误读成自由文本摘要。

## What Changes

- 新增有界、冻结且可重建的 `HandoffPacket`，由协作状态和宿主能力投影生成。
- 交接包包含目标/范围、已验证事实、显式假设、未决副作用、能力与审批、checkpoint、停止条件和返回责任人。
- Planner、Generator、Evaluator 的 role task data 使用同一结构化交接包；resume 从持久状态重建，不持久化模型自由摘要。
- 对交接包计算稳定 digest，并在协作审计中只记录 digest、角色、phase、attempt 和边界计数，不记录目标正文、文件内容、凭据或完整 receipt。
- 未决外部副作用只投影 manager-owned receipt label、phase 和 dispatch certainty；不自动重放、不自动解决。
- 单 Agent 默认路径、现有 Submit 门、Duo/Triad 串行编排和 `CollaborationReport` 既有字段保持兼容。

## Capabilities

### New Capabilities

- `structured-collaboration-handoff`: Duo/Triad 角色间的结构化交接协议。

### Modified Capabilities

- `runtime-collaboration`: role task data、resume 和审计增加有界 handoff 投影，不改变完成/拒绝/取消语义。

## Impact

- 运行时：`src/forgeagent/collaboration.py` 及协作测试、文档。
- 不新增 scheduler、Agent 网络、资源租约管理、数据库、endpoint、依赖或单 Agent 默认上下文。
- PyPI 发布、正式 tag、远程 push 和 `publish-v0-1-0` change 不在范围内，继续暂停。

```

## openspec/changes/structured-collaboration-handoff/design.md

- Source: openspec/changes/structured-collaboration-handoff/design.md
- Lines: 1-55
- SHA256: a7b5a323fb616c2621f5efbcde0d07ec50bc9ca911618a3dc63da396ded36627

```md
# 结构化协作交接设计

## Context

Duo/Triad 的持久 state 已经是恢复事实源：goal、plan/plan_digest、last_evaluation、phase、attempt、revision、usage 和 stop reason 均经过严格验证。当前 `_role_task_data()` 只拼接部分字段，且不同角色收到的上下文边界依赖调用方；这使交接语义难以审计，也没有统一表示副作用未决、能力/审批和返回责任。

## Goals / Non-Goals

### Goals

- 定义单一 `HandoffPacket`，由持久 state、当前角色和宿主能力确定性生成。
- 覆盖目标/范围、已验证事实、假设、未决副作用、能力/审批、checkpoint、停止条件和返回责任。
- 对传入 role task 的内容做严格结构化、固定上限和 secret/path masking；包可从 resume state 重建。
- 记录稳定 handoff digest，支持事实和风险追溯，不泄露正文或凭据。

### Non-Goals

- 不把模型自由摘要写入持久 state，不信任模型自报事实、权限或副作用状态。
- 不转移线程/会话控制权，不新增 scheduler、lease、消息总线、远程 Agent 或自动恢复。
- 不改变现有 SubmitCandidate/SubmitEvaluation、receipt 决策、停止原因或报告字段。

## Decisions

### 1. Packet 是投影，不是新事实源

`HandoffPacket` 使用严格 Pydantic 模型，字段均为有界 tuple/enum/安全文本。事实来自 `plan`、`last_evaluation`、`phase`、attempt/revision 和 receipt store 查询；假设字段默认显式空 tuple，不能由模型自由填充。范围由目标和冻结计划的稳定计数/摘要构成，避免把完整目标重复写入审计。

### 2. 能力和审批采用宿主声明

Planner 只产生 planning 交接；Generator 交接只声明当前 registry 的工具名集合（不含参数/凭据）和 `confirmation_available`；Evaluator 交接声明只读工具/冻结检查 ID（不含命令）。返回责任固定为下一角色或 `caller`，不允许模型修改。

### 3. 副作用采用安全收据投影

若宿主提供 receipt store，packet 只包含当前 collaboration/loop/task 关联的 open receipt 数量及每条的 public server/tool label、phase、dispatch certainty；没有 store 时为显式空值。packet 不提供 retry/resolve 决策，也不让角色把 receipt 当作已完成事实。

### 4. 传递、恢复和审计

每个 role task data 根部带 `handoff` 对象和 `handoff_digest`。旧 `loop_context` 继续作为不可信附加字段，仅 Generator 可见。resume 读取 state 后重新生成相同 packet；`collaboration.handoff` 审计只记录角色、phase、attempt、revision、digest 前缀、事实/风险计数和返回责任，不记录正文。

## Risks / Trade-offs

- 每个角色会增加少量 JSON 上下文；通过计数、短标签和有界 evidence 控制，不把完整目标/文件内容复制到每次 handoff。
- 收据只投影 open 状态，不能证明外部动作已解决；这是刻意的 fail-closed 设计，决策仍归用户或上层策略。
- 当前模型不表达资源租约，因为项目尚无租约所有权；将其写成 `none` 比伪造租约更安全。

## Migration Plan

1. 先增加模型、packet builder、digest 和失败边界测试。
2. 将三个 role 的 task data 切换到 packet；保留既有字段和 loop_context 兼容。
3. 接入 receipt/能力投影和 handoff audit。
4. 更新 runtime-collaboration、威胁模型和里程碑证据，执行全量门禁。

## Open Questions

- 若未来需要真正的 Agent 控制权转移，必须另立 change 定义 worker 生命周期、租约、重启和冲突恢复；本 change 不预留隐式转移语义。

```

## openspec/changes/structured-collaboration-handoff/tasks.md

- Source: openspec/changes/structured-collaboration-handoff/tasks.md
- Lines: 1-19
- SHA256: e9443ef4e87b2ee1cca6c825a7103f367b27b6e6b4a8d84128b959363b843ba3

```md
# 实施任务

## 1. 契约与投影

- [ ] 1.1 增加严格、有界、可重建的 `HandoffPacket`、digest 和角色/phase/return-owner 枚举。
- [ ] 1.2 从 CollaborationState、registry、checks 和可选 receipt store 生成 host-owned packet；为无 receipt store 明确 unavailable。
- [ ] 1.3 增加 packet masking、路径/控制字符、重复重建、未决 receipt 和能力边界测试。

## 2. 角色交接与恢复

- [ ] 2.1 将 Planner/Generator/Evaluator task data 统一改为包含 `handoff` 与 `handoff_digest`，保留旧字段和 loop_context 兼容。
- [ ] 2.2 为 role start 发出有界 `collaboration.handoff` 审计事件；不得记录正文、命令、路径、secret 或完整 receipt id。
- [ ] 2.3 增加 Duo/Triad、拒绝重试、evaluator resume、loop resume 和 Single 不变的回归测试。

## 3. 文档与验证

- [ ] 3.1 更新 runtime-collaboration、threat-model 和协作使用文档，记录 handoff 的责任边界与明确不做项。
- [ ] 3.2 运行专项测试、完整 pytest、Ruff、格式检查、build 和 OpenSpec strict。
- [ ] 3.3 最终进行两轮自评，检查模糊、错误、过度保守、前后不一致和遗漏；发现问题立即修复并复验，保持 PyPI 发布暂停。

```

## openspec/changes/structured-collaboration-handoff/specs/runtime-collaboration/spec.md

- Source: openspec/changes/structured-collaboration-handoff/specs/runtime-collaboration/spec.md
- Lines: 1-18
- SHA256: 0868ad86efc9f4df28414c91021182b6f6d8b86fe9ea48187a5884abb220df23

```md
# runtime-collaboration Specification Delta

## MODIFIED Requirements

### Requirement: 协作模式使用隔离角色与串行编排
ForgeAgent SHALL 提供 `single`、`duo` 和 `triad` 三种运行模式。Duo MUST 按 Generator → Evaluator 串行执行；Triad MUST 按 Planner → 确认 → Generator ⇄ Evaluator 串行执行。每个角色 MUST 使用独立 Task、conversation、runtime、tool registry 与模型 client，不得共享另一角色的模型历史或可变执行状态。角色边界 MUST 传递由持久 state 和宿主能力投影生成的有界结构化 handoff；该 handoff 不得成为角色间共享可变执行状态。

#### Scenario: Duo 角色隔离
- **WHEN** 用户以 Duo 模式执行任务
- **THEN** Generator 与 Evaluator 分别创建独立 Task，Evaluator 只接收原始目标、冻结验收输入、允许根目录中的外部可观察产物和当前结构化 handoff

#### Scenario: Triad 严格串行
- **WHEN** 用户以 Triad 模式执行任务
- **THEN** Planner 完成且计划确认后才创建 Generator，Generator 提交后才创建 Evaluator，v1 不并行运行角色；每个边界都生成新的有界 handoff

#### Scenario: 单角色兼容
- **WHEN** 任务选择 single
- **THEN** 系统沿用既有单 Task 路径，不创建 Planner、Evaluator 或协作 handoff 状态

```

## openspec/changes/structured-collaboration-handoff/specs/structured-collaboration-handoff/spec.md

- Source: openspec/changes/structured-collaboration-handoff/specs/structured-collaboration-handoff/spec.md
- Lines: 1-55
- SHA256: 1eb98e8b7855ceecd09bb30d107c17525e4a972272bd4309a316c26d14f8b801

```md
# structured-collaboration-handoff Specification

## ADDED Requirements

### Requirement: Collaboration roles exchange a bounded structured handoff

ForgeAgent SHALL create a validated `HandoffPacket` for each Planner, Generator and Evaluator boundary. The packet MUST contain bounded goal/scope projection, verified facts, explicit assumptions, open side-effect receipt projection, capability/approval projection, checkpoint, stop conditions, and a fixed return owner. Model-generated free-form summaries MUST NOT become durable handoff facts.

#### Scenario: Generator receives Planner handoff
- **WHEN** a Triad plan is submitted and confirmed
- **THEN** the Generator task data contains a validated handoff with the frozen plan digest, current phase, verified facts, explicit empty-or-bounded assumptions, capability/approval projection and return owner `evaluator`

#### Scenario: Evaluator receives Generator handoff
- **WHEN** the Generator successfully submits the current Candidate
- **THEN** the Evaluator task data contains a handoff tied to the current generator attempt and revision, lists only its read-only capabilities/frozen checks, and returns responsibility to `caller`

#### Scenario: Rejected Candidate returns to Generator
- **WHEN** Evaluator submits a failing verdict and the runner starts a new Generator attempt
- **THEN** the handoff preserves the frozen plan digest, includes bounded failed evaluation facts, identifies the current attempt and revision, and returns responsibility to `evaluator`

### Requirement: Handoff packets are deterministic and resumable

ForgeAgent SHALL derive handoff packets only from validated collaboration state and host-owned projections. The same state, role, attempt and capability inputs MUST produce the same packet and digest. Resume MUST rebuild the packet from durable state rather than trusting an old model summary. Handoff persistence MUST NOT change existing collaboration state transition or completion invariants.

#### Scenario: Resume reconstructs the same handoff
- **WHEN** a collaboration resumes from an evaluator phase with an empty verdict
- **THEN** the new Evaluator receives the same handoff digest for the same state and host capability projection, and no in-memory pre-crash summary is required

#### Scenario: Handoff input contains unsafe text
- **WHEN** goal, evidence, receipt labels or loop context contain secrets, absolute paths or control characters
- **THEN** the packet and task data use existing masking/bounded text rules, while routing and receipt ownership retain raw internal identities only where already required

### Requirement: Handoff exposes risk and authority without granting authority

ForgeAgent SHALL project open receipts using only public server/tool labels, phase and dispatch certainty, and SHALL mark unresolved actions as requiring explicit reconciliation. Capability and approval fields MUST be host-derived summaries; the packet MUST NOT grant new tools, bypass confirmation, resolve receipts, replay actions, or alter role ownership.

#### Scenario: Open external receipt is present
- **WHEN** a role boundary has an open external-action receipt
- **THEN** the handoff reports a bounded unresolved receipt projection and requires explicit reconciliation before retry; it does not call `resolve()` or replay the action

#### Scenario: No receipt store is available
- **WHEN** a role runs without a receipt store
- **THEN** the handoff explicitly reports that receipt visibility is unavailable rather than claiming there are no external actions

### Requirement: Handoff audit is bounded and compatible

ForgeAgent SHALL emit a handoff audit event containing only role, phase, attempt, revision, digest prefix, bounded counts, and return owner. Existing `CollaborationReport` fields, Single mode behavior, role Submit gates, loop context compatibility, and CLI/HTTP public report shape MUST remain unchanged.

#### Scenario: Handoff audit is emitted
- **WHEN** a role task starts with a handoff packet
- **THEN** audit contains a stable digest prefix and counts but no goal prose, plan text, file content, command, secret, absolute path or full receipt identifier

#### Scenario: Single mode remains unchanged
- **WHEN** a task uses Single mode
- **THEN** no collaboration handoff is created and the existing `TaskOutcome` path is used

```
