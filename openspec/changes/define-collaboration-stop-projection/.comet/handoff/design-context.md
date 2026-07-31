# Comet Design Handoff

- Change: define-collaboration-stop-projection
- Phase: design
- Mode: compact
- Context hash: 114010c4c045dfe965b3440f0502b224c4143d5441b3abb11efce1b1d401921d

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/define-collaboration-stop-projection/proposal.md

- Source: openspec/changes/define-collaboration-stop-projection/proposal.md
- Lines: 1-27
- SHA256: 94500864ba98fdf5440ff6f6f8f5be9833aef805622c240c0511974f0c7d803e

```md
## Why

CollaborationRunner 当前把多数角色 Task 非完成原因压缩为 `role_failed`，并且没有完整表达资源耗尽、等待输入和阻塞语义；同时，角色执行所需的原始 goal 与公开 handoff goal 依赖同一构造路径，容易在修复路径泄漏时误伤合法执行意图。M39 需要在 Duo 验收契约变更前先稳定这一投影边界。

## What Changes

- 定义 Task 和 Loop 原因到 Collaboration `status`、`stop_reason`、`attention` 的完整确定性投影。
- 保留 `rejection_limit` 等正常停止原因，并透传 `max_rounds`、`wall_clock`、`token_budget`、`token_usage_unavailable` 等资源耗尽原因。
- 将 `needs_info` 投影为 `needs_input`，将 `blocked` 和未决外部动作投影为可恢复阻塞，而不是内部失败。
- 保持 auth/invalid-request、状态损坏和角色协议错误为失败终态，并继续屏蔽原始异常正文。
- 分离角色执行 goal 与公开 handoff goal：内部任务数据保留合法绝对路径，HandoffPacket、报告与审计只使用有界脱敏投影。
- 为公开报告增加兼容的 attention 投影，不移除既有 status/reason 字段。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `runtime-collaboration`：明确 Collaboration 终态原因和 attention 的来源映射。
- `structured-collaboration-handoff`：明确内部执行 goal 与公开 handoff/audit 投影的信任边界。

## Impact

影响 `src/forgeagent/collaboration.py` 及 Collaboration、Loop、HTTP、handoff 相关测试和规范。不新增依赖，不改变 single TaskOutcome，不执行 PyPI、tag、push 或发布自动化。

```

## openspec/changes/define-collaboration-stop-projection/design.md

- Source: openspec/changes/define-collaboration-stop-projection/design.md
- Lines: 1-48
- SHA256: 8d727a572d6fa07eba03dea53c1b9193f247c45cad7fc98193acbb2ff6a47df5

```md
## Context

Task 已提供稳定 `reason` 与可选 `attention`，Loop 也有独立的预算、等待输入、阻塞和失败原因；CollaborationRunner 却只识别少数不可恢复错误，其余非完成结果大多变成 `role_failed`。此外，`state.goal` 是角色实际执行输入，`HandoffPacket.goal` 是跨边界公开投影，二者用途不同但目前没有显式命名其信任边界。

本 change 必须保持既有 Collaboration JSON 兼容、M27 路由迁移兼容、结构化 Submit 门禁和公开审计安全边界，不引入新的调度器、异常正文或发布动作。

## Goals / Non-Goals

**Goals：**

- 让 Task/Loop 的停止信号稳定映射为 Collaboration 的正常停止、资源耗尽、需要输入、阻塞、取消或失败。
- 公开报告以附加式 attention 表达恢复责任，同时保留既有 status/reason。
- 保留内部执行 goal 的合法路径，公开 handoff/report/audit 继续去除绝对路径、secret 和原始 prompt 正文。
- 用单一确定性函数承载映射，便于单元测试和后续调用方复用。

**Non-Goals：**

- 不让 CollaborationRunner 直接运行或嵌套 LoopRunner。
- 不修改 Loop handoff 自由文本结构；该议题留给独立 change。
- 不改变 Duo 验收计划；该议题由 M39 第三个 change 处理。
- 不新增依赖、HTTP endpoint、发布自动化、tag、push 或 PyPI 工作。

## Decisions

1. **保留原始稳定原因，按终态分组。** 投影函数返回 `(status, stop_reason, attention)`。`needs_info -> stopped/needs_input`，`blocked -> stopped/blocked`，资源上限保留其原 reason 并归入 stopped，`cancelled` 归入 cancelled，auth/invalid-request 和协议/状态错误归入 failed。把资源原因统一改名为 `resource_exhausted` 会丢失调用方所需诊断，因此不采用。

2. **Task 与 Loop 使用同一输入词表，但不制造不存在的嵌套。** 当前角色返回 `TaskOutcome`，因此 Runner 直接使用 Task reason；同时提供并测试 Loop 原因投影表，供外层或后续适配复用。LoopRunner 仍负责自己的预算，CollaborationRunner 不复制计时器和 token 预算逻辑。

3. **attention 为兼容的公开附加字段。** CollaborationState/Report 增加可选 `Attention`。只有 `needs_input` 和 `blocked` 停止持久化对应 attention；预算停止与普通终态由公开 HTTP 层根据稳定 reason 派生 ready，不把它们误报为等待外部动作。

4. **执行输入与公开投影分离。** `_role_task_data` 和 `_planner_task_data` 的 `goal` 继续取 `state.goal`，保证 `/data/input.csv` 等合法路径可执行；`build_handoff_packet` 明确通过公开 goal helper 构造 `HandoffPacket.goal`。审计只记录 digest、枚举和计数，不记录两个 goal 视图正文。

5. **失败关闭且不泄漏。** 未知 Task/Loop reason 归为 `failed/role_failed`，不把任意字符串加入公开 stop reason。异常处理继续只记录固定事件和异常类型，不记录 message、路径、secret 或 goal。

## Risks / Trade-offs

- [风险] 新 stop reason 使旧严格枚举校验失败。→ 扩展 CollaborationState 的固定允许集合，并增加旧 JSON 与 HTTP 回归测试；不删除旧原因。
- [风险] attention 与 status/reason 漂移。→ 在模型 validator 中约束 needs_input/blocked 必须携带匹配 attention，其他终态不得持久化待处理 attention。
- [风险] handoff task data 同时出现原始 goal 和脱敏 goal。→ 这是有意的信任边界：前者只供内部角色执行，后者是模型间公开摘要；审计测试禁止记录任一正文。
- [风险] 过度扩展为通用状态机。→ 只实现静态映射常量和小型纯函数，不新增配置或注册机制。

## Migration Plan

旧 Collaboration snapshot 没有 attention 时继续加载；已有 stop reason 保持有效。新增原因只在对应 Task/Loop 信号出现时写入。回滚时可移除新增字段和映射，不需要磁盘数据重写。

## Open Questions

无。M39 已授权在两轮自评后采用推荐方案。

```

## openspec/changes/define-collaboration-stop-projection/tasks.md

- Source: openspec/changes/define-collaboration-stop-projection/tasks.md
- Lines: 1-21
- SHA256: 892d3a0309adc818d567253d7614ab871dfeb88b8460ee5a6291ae39c9ca5231

```md
## 1. 投影契约测试

- [ ] 1.1 为 Task/Loop 已知原因到 Collaboration status、stop reason 和 attention 的映射编写失败测试。
- [ ] 1.2 为资源耗尽、needs input、blocked、cancelled、正常打回和失败类别补齐 Runner/模型回归测试。

## 2. 执行与公开目标边界

- [ ] 2.1 为合法绝对路径在内部 role task data 中保留、在公开 handoff 中脱敏编写失败测试。
- [ ] 2.2 为 handoff/report/audit 不泄漏 secret、raw goal、绝对路径或原始异常编写回归测试。

## 3. 最小实现

- [ ] 3.1 实现单一确定性 stop projection helper，扩展 CollaborationState/Report 允许集合和安全 attention 字段。
- [ ] 3.2 在角色失败边界应用投影，同时保持结构化提交、取消、状态失败和恢复语义。
- [ ] 3.3 将内部 execution goal 与 `HandoffPacket.goal` 的 public projection 显式分离。

## 4. 验证与收尾

- [ ] 4.1 运行 focused pytest、Ruff、format 和 OpenSpec strict，并修复回归。
- [ ] 4.2 运行全量 pytest 与构建验证，记录不执行 PyPI、tag、push 或发布自动化。
- [ ] 4.3 完成两轮代码/契约自评审并记录验证报告。

```

## openspec/changes/define-collaboration-stop-projection/specs/runtime-collaboration/spec.md

- Source: openspec/changes/define-collaboration-stop-projection/specs/runtime-collaboration/spec.md
- Lines: 1-26
- SHA256: 7cec6d7d97b6dc79ebbb0ea62280c8fbc8e9cdb160042f36e6218a720114c203

```md
## MODIFIED Requirements

### Requirement: 协作报告稳定、有界且兼容
协作执行 MUST 返回加法式稳定报告，包含 mode、终态、稳定原因、角色尝试计数、计划项计数、通过/失败计数、打回次数、累计轮次、normalized usage 与可选的有界 attention。报告 MUST NOT 包含完整目标、计划正文、模型回复、工具参数、文件内容、绝对路径、credential、原始异常或未掩码证据。普通 `TaskOutcome` 的既有字段与语义 MUST 保持兼容。

Task 与 Loop 的已知停止信号 MUST 使用确定性投影：正常打回上限保持 `stopped/rejection_limit`；`needs_info` 映射为 `stopped/needs_input`；`blocked` 和未决外部动作映射为 stopped 的阻塞原因；`max_rounds`、`wall_clock`、`token_budget`、`token_usage_unavailable` 与 `consecutive_failures` MUST 保留具体资源原因并映射为 stopped；`cancelled` 映射为 cancelled；auth、invalid-request、checkpoint/state/protocol 损坏与其他不可恢复角色错误映射为 failed。未知原因 MUST fail closed，不得成为任意公开枚举。

#### Scenario: 安全终态投影
- **WHEN** CLI 或 HTTP 输出协作终态
- **THEN** 输出只包含稳定枚举、计数、模型标识、可选安全 attention 和经过掩码截断的逐项证据摘要

#### Scenario: 普通结果未改变
- **WHEN** single 任务结束
- **THEN** 现有调用方仍收到原 `TaskOutcome` 形状，不需要解析协作字段

#### Scenario: 资源耗尽原因透传
- **WHEN** 内层 Task 或外层 Loop 因 `max_rounds`、`wall_clock`、`token_budget`、`token_usage_unavailable` 或 `consecutive_failures` 停止
- **THEN** Collaboration 投影为 `stopped` 并保留该稳定原因，不把它误报为 `rejection_limit` 或 `role_failed`

#### Scenario: 需要输入和阻塞保持可恢复
- **WHEN** 内层 Task 报告 `needs_info`，或 Task/Loop 报告 `blocked`、`external_action_pending`
- **THEN** Collaboration 投影为 `stopped`，分别使用 `needs_input` 或稳定阻塞原因，并附带不含敏感正文的匹配 attention

#### Scenario: 不可恢复错误保持失败
- **WHEN** 角色遭遇 auth、invalid-request、状态损坏、checkpoint 损坏、无效结构化提交或其他不可恢复错误
- **THEN** Collaboration 报告为 `failed` 且只暴露固定失败原因，不包含原始异常正文

```

## openspec/changes/define-collaboration-stop-projection/specs/structured-collaboration-handoff/spec.md

- Source: openspec/changes/define-collaboration-stop-projection/specs/structured-collaboration-handoff/spec.md
- Lines: 1-19
- SHA256: f27000e9d9236e31438656d82a17a9a9a9320bc54672fd338ce78c42d1d8c5d4

```md
## MODIFIED Requirements

### Requirement: Handoff packets are deterministic and resumable

ForgeAgent SHALL derive handoff packets only from validated collaboration state and host-owned public projections. The same state, role, attempt and capability inputs MUST produce the same packet and digest. Resume MUST rebuild the packet from durable state rather than trusting an old model summary. Handoff persistence MUST NOT change existing collaboration state transition or completion invariants.

The raw collaboration goal used to execute Planner, Generator and Evaluator tasks MUST remain an internal execution input and MAY retain a legitimate absolute path required by the task. `HandoffPacket.goal`, CollaborationReport and handoff audit MUST use a separate bounded public projection that masks secrets, absolute paths and unsafe characters. Public audit MUST NOT contain either the raw goal or the public goal prose.

#### Scenario: Resume reconstructs the same handoff
- **WHEN** a collaboration resumes from an evaluator phase with an empty verdict
- **THEN** the new Evaluator receives the same handoff digest for the same state and host capability projection, and no in-memory pre-crash summary is required

#### Scenario: Handoff input contains unsafe text
- **WHEN** goal, evidence, receipt labels or loop context contain secrets, absolute paths or control characters
- **THEN** the packet's public fields use existing masking and bounded text rules, while internal role task data preserves only the validated execution goal and routing or receipt ownership retains raw internal identities only where already required

#### Scenario: Legitimate execution path remains available
- **WHEN** a validated goal instructs a role to process an absolute path such as `/data/input.csv`
- **THEN** the internal role task goal retains that path for execution, while `HandoffPacket.goal`, CollaborationReport and audit contain no absolute path or raw goal body

```
