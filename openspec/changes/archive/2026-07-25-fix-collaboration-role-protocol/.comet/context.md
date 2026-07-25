# Comet Design Handoff

- Change: fix-collaboration-role-protocol
- Phase: design
- Mode: compact
- Context hash: 7b59bf8b0f57fc9c32177af3f69dbe233d4682f942147a6ee03880f3fdcdebf0

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/fix-collaboration-role-protocol/proposal.md

- Source: openspec/changes/fix-collaboration-role-protocol/proposal.md
- Lines: 1-36
- SHA256: 27a58f336d9698a7261f1b9af3202d7c4bc7fa3d9ab5eea2b20696822c0e7bc9

```md
## Why

M22 真实模型人类验收暴露出协作角色完成协议不可靠：Planner、Generator、Evaluator 可能在
未调用其结构化 Submit 工具时声明完成，或在产物已经正确时因额外的 standalone
`task_status` 轮次耗尽。Generator 还会尝试用 restricted Exec 重复验证刚由 FileWrite 写入
的宿主文件，文件视图差异导致无意义重试。提示增强能降低偏离概率，但不能形成确定性门。

## What Changes

- 新增 Generator 专用零载荷 `SubmitCandidate`，成功提交是进入 Evaluator 的唯一入口。
- 三个角色的 Submit 工具保存成功即完成角色；Step 截断同一响应中位于成功 Submit 之后的
  工具调用，不再要求额外 standalone `task_status`。
- Tool registry 显式登记唯一 required completion tool；Step 提供一次缺失 Submit 的结构化
  恢复机会，但不感知协作角色、phase 或工具名称。
- 复用现有 phase、attempt 和 `last_evaluation` 表达 Candidate 生命周期，保持
  `forgeagent.collaboration.v1` schema 不变。
- Runner 继续负责冻结计划、统计边界、pass/reject、拒绝上限、恢复和稳定失败映射。
- 更新三个角色提示、回归测试和真实模型 Triad 验收。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `runtime-collaboration`：增加结构化角色提交门、Candidate attempt 绑定和无歧义恢复语义。

## Impact

- 代码：`src/forgeagent/tools.py`、`src/forgeagent/step.py`、
  `src/forgeagent/collaboration.py`
- 测试：Step、协作工具、Runner、Planner、Loop collaboration 与真实模型人工验收
- 文档：`runtime-collaboration` delta spec、技术设计与实施计划
- API、依赖、公开报告和持久化 schema：不变

```

## openspec/changes/fix-collaboration-role-protocol/design.md

- Source: openspec/changes/fix-collaboration-role-protocol/design.md
- Lines: 1-51
- SHA256: a2f201bbe21e2b6a66c9e765dbd5db4c21b61d8e97fd3cdb42b46ec32453b444

```md
## Context

协作角色使用独立 Task 和 registry。现有 Runner 把 Generator 的普通 Task completion 直接视为
可进入 Evaluator，并要求 Planner/Evaluator 在 Submit 成功后再发送 standalone
`task_status`。真实模型证明这两种隐式边界都不稳定。CollaborationStore 已提供 revision CAS，
因此可以在不新增持久字段的情况下把结构化提交作为原子状态边界。

## Goals / Non-Goals

**Goals:**

- 只有成功的结构化 Submit 才能完成 Planner、Generator 或 Evaluator 角色。
- Generator 候选与当前 attempt 绑定，拒绝、恢复和 verdict 不跨候选复用。
- Evaluator 独占外部可观察验收；Generator 不承担宿主冻结检查。
- single、Loop single、公开报告、权限和 collaboration schema 保持兼容。

**Non-Goals:**

- 不新增 Candidate manifest、逐项 Generator 证据或宿主检查权限。
- 不引入动态工具锁、provider 原生 function calling、新依赖或新状态字段。
- 不推断崩溃前尚未持久化的 rounds/usage。

## Decisions

1. `SubmitCandidate` 使用空参数 `{}`。冻结 plan 与 allowed root 是 Evaluator 的权威输入。
2. `ToolOutcome` 增加默认关闭的通用成功终止信号；Submit 工具仅在 CAS 保存成功后置位。
3. Step 按 parser 的确定性输出顺序执行工具（文本 ToolCall 后接 provider 原生 tool_calls）。
   第一个成功终止工具完成任务并截断后续调用；先前工具和
   非致命解析错误不回滚已持久化提交。
4. ToolRegistry 显式登记至多一个 required completion tool。缺失 Submit 的 completion 声明
   获得一次恢复提示，重复违规稳定失败。
5. `SubmitCandidate` 原子执行 `phase=evaluator`、`generator_attempts+1`、清空旧 verdict。
   `SubmitEvaluation` 原子保存 verdict、`evaluator_attempts+1`，仍保持 evaluator phase。
6. Runner 对成功提交只补记 rounds/usage；失败角色仍在角色边界计数。Runner 独占 verdict
   判定、rejection limit 和终态转换。
7. 拒绝回到 Generator 时保留旧 verdict 供崩溃恢复重建反馈；下一 Candidate 提交时才清空。

## Rejected Alternatives

- 隐式根据文件或工具活动判断 Candidate ready：部分写入和 clean completion 无法可靠区分。
- Candidate 携带 artifact manifest 或逐项证据：信息非权威并模糊 Generator/Evaluator 职责。
- 给 Generator 宿主冻结检查权限：扩大权限和成本，且重复 Evaluator 工作。
- Submit 后等待 standalone completion 或动态锁写工具：增加轮次与恢复复杂度。
- 新增 Candidate/evaluation 关联字段：现有 phase、attempt、verdict 已足够表达状态。

## Risks / Trade-offs

- 通用成功终止信号会改变 Submit 工具的 Step 生命周期；通过默认 false 和 single 回归隔离风险。
- Submit 已保存而统计尚未保存时崩溃会丢失本轮 rounds/usage；选择不做不可靠推断。
- registry required completion tool 若误配多个会产生歧义；注册时 fail fast。
- 提交前工具失败后仍可能提交不完整候选；这是允许的，Evaluator 必须独立发现并拒绝。

```

## openspec/changes/fix-collaboration-role-protocol/tasks.md

- Source: openspec/changes/fix-collaboration-role-protocol/tasks.md
- Lines: 1-20
- SHA256: 1d04bcf5e58519e89079ad77e9059175565c0cd6d769cbb4be89e96ebe9d8f96

```md
## 1. 通用提交终止协议

- [ ] 1.1 为 ToolOutcome 和 ToolRegistry 增加通用 completion signal 与唯一 required tool 元数据
- [ ] 1.2 以 TDD 实现 Step 的顺序截断、一次恢复和 single 兼容行为

## 2. Candidate 状态机

- [ ] 2.1 以 TDD 新增零载荷 SubmitCandidate 及 Generator registry 组合
- [ ] 2.2 让三个 Submit 工具原子计数并立即完成角色
- [ ] 2.3 重构 Runner 成功/失败边界、verdict 判定和恢复路径，避免 attempt 双计

## 3. 协议与模式回归

- [ ] 3.1 更新 Planner、Generator、Evaluator 提示与 required Submit 失败映射
- [ ] 3.2 覆盖 Duo、Triad、Loop duo/triad、single、冻结计划、安全与审计回归

## 4. 验证

- [ ] 4.1 运行专项测试、ruff、完整 pytest 和 OpenSpec/Comet guard
- [ ] 4.2 在两个全新临时目录连续运行真实模型 Triad，并独立验证 pytest 与 calc.py CLI 输出

```

## openspec/changes/fix-collaboration-role-protocol/specs/runtime-collaboration/spec.md

- Source: openspec/changes/fix-collaboration-role-protocol/specs/runtime-collaboration/spec.md
- Lines: 1-53
- SHA256: 81fba9b5b631b196b7e98300817ceb8d6b8be02b18bdd926d0f562682b2436f1

```md
## ADDED Requirements

### Requirement: 协作角色使用结构化提交门完成工作
Planner、Generator 和 Evaluator MUST 分别通过本角色 registry 中唯一的结构化 Submit 工具完成
角色。成功 Submit MUST 在持久状态保存后立即完成当前角色，并 MUST 阻止同一响应中后续工具
执行。普通 prose 或 `task_status.completed` MUST NOT 代替 required Submit；运行时 MAY 对首次
缺失提交提供一次有界结构化恢复提示。未注册 required Submit 的 single 模式 MUST 保持既有
完成语义。

#### Scenario: 成功提交立即完成角色
- **WHEN** 协作角色在同一响应中先执行合法准备工具，再成功调用本角色 Submit 工具，并在其后声明其他工具调用
- **THEN** 运行时按 parser 的确定性工具顺序执行到 Submit，将持久状态保存并完成角色，且不执行或审计 Submit 后的工具

#### Scenario: 完成声明不能替代提交
- **WHEN** 协作角色声明 completed 但未成功调用 required Submit
- **THEN** 运行时首次返回精确的缺失工具恢复提示，重复绕过提交时以 `invalid_role_submission` 结束该协作

#### Scenario: Single 完成语义保持兼容
- **WHEN** single Task 使用未登记 required completion tool 的 registry
- **THEN** Step 保持既有工具、prose recovery 和 `task_status` 完成行为

### Requirement: Generator Candidate 与当前 attempt 原子绑定
在 Duo/Triad 中，Generator MUST 成功调用零载荷 `SubmitCandidate` 才能进入 Evaluator。
`SubmitCandidate` MUST 在同一次 revision-checked 保存中递增 `generator_attempts`、将 phase 切换为
`evaluator` 并清空旧 `last_evaluation`。Generator 的普通 Task completion MUST NOT 推进 phase。
Evaluator MUST NOT 在当前 Candidate 尚未提交时启动。

#### Scenario: 当前 Candidate 提交后进入验收
- **WHEN** Generator 在 generator phase 成功调用 `SubmitCandidate` 且 state revision 未过期
- **THEN** 状态原子变为 evaluator phase、Generator attempt 恰好增加一次、旧 verdict 被清空，Runner 才能启动 Evaluator

#### Scenario: Candidate 提交失败不推进 phase
- **WHEN** `SubmitCandidate` 在错误 phase、过期 revision 或无效调用中失败
- **THEN** phase、attempt 和 verdict 保持不变，工具返回结构化失败并允许当前角色在剩余轮次修正

### Requirement: Verdict 只属于当前已提交 Candidate
Evaluator MUST 只验收 evaluator phase 中当前已提交的 Candidate。`SubmitEvaluation` MUST 在同一次
revision-checked 保存中写入覆盖冻结计划的 verdict 并递增 `evaluator_attempts`，但 MUST NOT 自行
决定 pass、reject、rejection count 或协作终态。拒绝回到 Generator 时，运行时 MUST 暂存旧 verdict
用于恢复拒绝反馈；下一次 `SubmitCandidate` 成功时 MUST 清空该 verdict。恢复时 evaluator phase
中的空 verdict MUST 重跑 Evaluator，非空 verdict MUST 直接交由 Runner 判定且不得重复调用模型。

#### Scenario: 拒绝后恢复 Generator 反馈
- **WHEN** Evaluator 提交失败 verdict，Runner 未达 rejection limit 并在进入新 Generator 前发生恢复
- **THEN** generator phase 保留旧 verdict，新的 Generator Task 收到该有界拒绝证据，且旧 verdict 不能被当作新 Candidate 的结果

#### Scenario: 已提交 verdict 恢复时不重复验收
- **WHEN** collaboration 从 evaluator phase 且 `last_evaluation` 非空的持久状态恢复
- **THEN** Runner 直接执行 pass/reject 判定，不创建新的 Evaluator Task，也不重复增加 evaluator attempt

#### Scenario: 待验收 Candidate 恢复
- **WHEN** collaboration 从 evaluator phase 且 `last_evaluation` 为空的持久状态恢复
- **THEN** Runner 为当前已提交 Candidate 创建 Evaluator Task，并要求结构化 `SubmitEvaluation`

```
