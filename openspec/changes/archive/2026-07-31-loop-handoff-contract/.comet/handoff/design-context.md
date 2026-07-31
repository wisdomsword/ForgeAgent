# Comet Design Handoff

- Change: loop-handoff-contract
- Phase: design
- Mode: compact
- Context hash: d84b6d9fff8f94525047ba8dbf312dae88b41f9a5614eba2bebf1a798d667a76

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/loop-handoff-contract/proposal.md

- Source: openspec/changes/loop-handoff-contract/proposal.md
- Lines: 1-27
- SHA256: d878ccd8122cdfb811c43bd7b2258e976d717877ef983e68919b96bb37e5dd8a

```md
## Why

Loop checkpoint 当前把模型提交的自由文本直接作为下一轮交接状态，导致模型可以间接改写宿主拥有的执行边界，也让旧字符串兼容、恢复提示和“不重放副作用”语义缺少统一契约。M40 需要把可提交进度收敛为有界、可验证的状态候选，并在旧 checkpoint 仍可读取的前提下明确恢复边界。

## What Changes

- 为 Loop handoff 引入宿主拥有的结构化状态，至少包含 `completed_items`、`open_questions` 和 `summary`。
- 将旧 JSON 中的字符串 `handoff` 只读迁移为结构化 `summary`；新写入使用稳定结构，保留公开 `schema` 键兼容性。
- 将 `Checkpoint` 工具限制为提交状态候选；目标、预算、权限、协作冻结状态、终态和恢复语义只能由宿主保留。
- 对提交缺失或可恢复校验失败提供有界恢复提示；恢复不执行无条件重放，尤其不重放副作用或未知收据动作。
- 增加旧 checkpoint、候选越权、迁移、恢复边界和 Loop 注入上下文的回归验收。

## Capabilities

### New Capabilities

- `loop-handoff-contract`: Loop handoff 的结构化状态、候选投影、兼容迁移和有界恢复契约。

### Modified Capabilities

- `loop-execution`: 修改 checkpoint handoff 的持久化、resume 注入和 Loop 专用 `Checkpoint` 提交边界；保留既有 Loop 终态、预算和公开报告语义。

## Impact

- 影响 `src/forgeagent/loop.py` 的 checkpoint 模型、Checkpoint 工具、resume 注入和失败恢复边界。
- 影响 `src/forgeagent/step.py` 的 required submission 恢复次数与不重放约束。
- 增加 Loop checkpoint、runner、Step 和 OpenSpec 严格校验测试；不新增依赖，不修改 CLI/HTTP 公共报告，不执行 PyPI、tag、push 或发布自动化。

```

## openspec/changes/loop-handoff-contract/design.md

- Source: openspec/changes/loop-handoff-contract/design.md
- Lines: 1-43
- SHA256: 647574325e4e665835d7bdd449920d843659b3c55eed990ae44c78772dff0bd0

```md
## Context

`LoopCheckpoint` 已经是冻结目标、预算、协作路由和累计计数的宿主快照，但 `handoff: str` 与 `CheckpointArgs.handoff: str` 仍由模型自由填写。`LoopRunner._render_suffix()` 会把这些字段送入下一轮提示，故 handoff 必须被视为不可信候选，而不是控制面输入。当前仓库还要求旧 checkpoint 使用 `schema` 键可加载，并且外部动作收据在未知状态时禁止静默重放。

## Goals / Non-Goals

**Goals:**

- 使用冻结的 `LoopHandoff` 结构保存有界完成项、未解问题和摘要。
- 使用独立的候选模型承接模型输出，只允许更新 handoff 内容字段；宿主保留目标、预算、权限、协作冻结状态、终态和恢复策略。
- 在加载时兼容旧字符串 handoff；新保存内容不再依赖自由字符串。
- 为缺失/失败提交提供有限恢复提示，且恢复只重新请求提交，不重放工具或外部动作。

**Non-Goals:**

- 不引入通用状态机、事件溯源、调度器或新的持久化后端。
- 不改变 LoopStopReason、Task/Collaboration 终态分类、公开 LoopReport 字段或外部收据协议。
- 不把 Loop handoff 与 Collaboration `HandoffPacket` 合并；不引入 LLM 自动摘要或拆解器。

## Decisions

1. **双模型边界。** `LoopHandoff` 是宿主持久化模型，使用冻结、禁止额外字段的 `completed_items`、`open_questions`、`summary` 字段；`LoopHandoffCandidate`/`CheckpointArgs` 只表达模型可提交的三项内容。CheckpointTool 从候选更新 handoff，其他 checkpoint 字段直接沿用当前快照。相比让模型提交完整 checkpoint，这能在 Pydantic 校验前后都阻断越权字段。
2. **兼容迁移。** `LoopCheckpoint` 的 before validator 接受旧字符串 `handoff`，转换为 `LoopHandoff(summary=<旧字符串>)`；缺失 handoff 使用空结构。读取旧文件不会原地改写，下一次正常保存才以结构化对象序列化。这样旧文件可恢复，且迁移不扩大读取权限。
3. **恢复边界。** required completion submission 的恢复提示由宿主计数并设置固定上限；普通 Task/Collaboration 保持一次恢复的兼容默认值，Loop 宿主任务显式允许两次，达到上限后失败。恢复消息只要求模型重新提交当前状态，不调用历史 ToolCall、不复制外部动作、不改变 receipt 状态。若已有未知/待处理收据，Loop 在现有 `external_action_pending` 门禁处停止。
4. **不可回退的进度。** `completed_items` 仍只能追加；`open_questions` 与 `summary` 可替换但受相同安全文本和大小限制。模型不能清除已完成项，也不能通过 handoff 候选改变 goal、budgets、permissions、collaboration_mode、plan_digest、status、stop_reason 或 attention。
5. **提示投影。** `_render_suffix()` 只注入结构化 handoff 的 JSON 投影，并显式标记为不可信 Loop 状态；公开报告继续只输出计数，不泄漏 handoff 正文。

## Risks / Trade-offs

- [旧 handoff 摘要可能包含历史模型文本] → 迁移复用既有 `safe_text`/secret masking 边界并限制长度；不把它当作指令执行。
- [一次恢复不足以纠正暂时性提交格式错误] → 允许有限次数的同一提交恢复提示，但明确禁止动作重放；超过上限转为失败，避免无限循环。
- [结构化 handoff 改变 checkpoint JSON 形状] → 仅对新保存文件改变 handoff 值形状，保留 `schema`、其他键和旧字符串读取兼容；增加 round-trip 与 legacy fixture 测试。

## Migration Plan

1. 先添加失败测试和 delta spec，覆盖结构、兼容加载、越权字段和恢复边界。
2. 实现模型与 CheckpointTool，再接入 Runner 注入和 Step 有界恢复。
3. 运行 focused/full pytest、Ruff、format、OpenSpec strict 和 `uv build`。
4. 不执行发布、tag 或 push；旧 checkpoint 不主动批量改写。

## Open Questions

- 无。字段范围、兼容方式和恢复上限均在本 change 中固定，并由测试锁定。

```

## openspec/changes/loop-handoff-contract/tasks.md

- Source: openspec/changes/loop-handoff-contract/tasks.md
- Lines: 1-17
- SHA256: 59b68b3bd21d32a4d308c3e583bb3c46d414103ef894fb60ef33997e62421853

```md
## 1. 契约与兼容性

- [x] 1.1 新增冻结的 `LoopHandoff` 与仅供模型提交的候选校验，复用有界安全文本规则并保持完成项只增不减。
- [x] 1.2 加载时迁移旧字符串 `handoff`，不得执行其中内容，并保持 `schema` JSON 别名往返兼容。
- [x] 1.3 更新 Loop checkpoint 与下一轮上下文注入以使用结构化 handoff，同时保持公开报告计数字段不变。

## 2. 恢复边界

- [x] 2.1 将 `CheckpointTool` 写入限制为候选拥有的 handoff 字段，并在持久化前拒绝控制面字段。
- [x] 2.2 增加宿主拥有的有限提交恢复上限，只请求纠正提交，不重放历史工具或外部动作。
- [x] 2.3 保持恢复期间待处理/未知外部收据的停止门禁。

## 3. 验证与文档

- [x] 3.1 增加回归测试：合法更新、旧数据迁移、schema 别名、控制面拒绝、完成项只增、上下文投影和有限非重放恢复。
- [x] 3.2 运行专项测试、全量 pytest、Ruff check/format、OpenSpec strict 校验和 `uv build`；修复回归但不发布。
- [x] 3.3 记录 M40 验收证据，更新 `ACTION_PLAN.md`，创建 `milestones/milestone_040.md`，更新 `milestones/latest` 并归档 Comet change。

```

## openspec/changes/loop-handoff-contract/specs/loop-execution/spec.md

- Source: openspec/changes/loop-handoff-contract/specs/loop-execution/spec.md
- Lines: 1-32
- SHA256: a1aca593a9976277ed19eddd1e2dad5985bcc7fb2bc3a2e19fdab9e6bdd6392a

```md
## MODIFIED Requirements

### Requirement: Loop checkpoint 是版本化、原子且有界的耐久状态
Loop SHALL 将 schema 版本、Loop 身份、原始目标、预算配置、累计预算、迭代计数、连续失败数、结构化 handoff、最近安全失败摘要和终态写入 checkpoint。结构化 handoff MUST 至少包含 `completed_items`、`open_questions` 和 `summary`，并 MUST 是宿主拥有的冻结状态；模型只能通过 Loop 专用 `Checkpoint` 工具提交这些字段的候选值，不得修改目标、预算、权限、协作冻结状态、attention、终态或恢复策略。checkpoint MUST 位于允许根目录内，MUST 使用原子替换写入，MUST 拒绝符号链接逃逸、未知字段、超限内容、无效状态组合和不支持的 schema 版本。每个 Loop ID 的 create 与 save MUST 使用稳定 lock file 的跨进程排他锁，将存在性或 expected revision 校验与原子替换纳入同一临界区；同一旧 revision 的重叠提交最多一个成功。Checkpoint 的 Pydantic 字段名 MAY 使用内部保留名，但序列化和反序列化 MUST 保持公开 JSON 键 `schema`，并兼容既有 checkpoint。旧 checkpoint 的字符串 handoff 和顶层完成项/未解问题 MUST 仅在加载时迁移为结构化 handoff；读取迁移 MUST NOT 执行或信任其中指令。

#### Scenario: 模型提交结构化进度候选
- **WHEN** Loop 专用 `Checkpoint` 工具收到合法的已完成条目、未解问题和摘要候选
- **THEN** 系统在返回工具成功反馈前原子持久化结构化 handoff，只更新候选拥有的字段，并保留此前已提交完成条目和全部宿主控制面字段

#### Scenario: 候选尝试修改控制面
- **WHEN** Checkpoint 提交包含目标、预算、权限、协作模式、计划摘要、attention、终态或恢复字段
- **THEN** 系统在写盘前拒绝未知字段，checkpoint 保持不变

#### Scenario: 旧字符串 handoff 加载
- **WHEN** 旧 checkpoint JSON 使用字符串 `handoff` 和顶层完成项/未解问题且其他字段有效
- **THEN** 系统将字符串仅投影为结构化 `summary`，保留完成项/未解问题，以 `schema` 键继续加载；下一次正常保存使用结构化 handoff 且不执行旧文本

#### Scenario: checkpoint 写入失败
- **WHEN** checkpoint 目录不可写、目标发生路径逃逸、lock file 不安全、加锁失败、原子替换失败或提交 revision 陈旧
- **THEN** `Checkpoint` 工具返回结构化失败，Loop 不声称进度已持久化，且失败可进入有界 Task 反馈环但不得触发历史动作重放

#### Scenario: checkpoint 内容或版本无效
- **WHEN** resume 读取到未知 schema、额外字段、冲突的新旧 handoff 投影、超限文本、无效计数或互相矛盾的终态
- **THEN** 系统在调用模型或工具前拒绝恢复，并保留原文件不变

#### Scenario: 同一旧 revision 跨进程重叠提交
- **WHEN** 两个进程都读取 revision N 并以 `expected_revision=N` 提交不同 checkpoint
- **THEN** 第一个锁内提交写入 revision N+1，第二个锁内重读后收到 stale revision 错误且不得覆盖第一份状态

#### Scenario: 不同 Loop ID 并行提交
- **WHEN** 两个进程同时保存不同 Loop ID
- **THEN** 它们使用不同稳定 lock file，不因全目录锁而互相串行化

```

## openspec/changes/loop-handoff-contract/specs/loop-handoff-contract/spec.md

- Source: openspec/changes/loop-handoff-contract/specs/loop-handoff-contract/spec.md
- Lines: 1-45
- SHA256: ef8d81718383daf02fc75a78bce21dd653d7326972a7a1fc3c4b949ff8f34f1f

```md
## ADDED Requirements

### Requirement: Loop handoff is host-owned and structured

The Loop checkpoint MUST persist a frozen, bounded handoff structure containing `completed_items`, `open_questions`, and `summary`. A model submission MUST be represented as a separate validated candidate and MUST NOT be able to change the frozen goal, budgets, permissions, collaboration mode, plan digest, attention, status, stop reason, or recovery policy.

#### Scenario: Valid candidate updates handoff
- **WHEN** the Loop `Checkpoint` tool receives valid candidate fields
- **THEN** it atomically saves only the handoff fields, preserves host-owned fields, and retains all previously completed items

#### Scenario: Candidate attempts control-plane mutation
- **WHEN** a checkpoint submission includes goal, budget, permission, status, stop reason, collaboration, plan, or recovery fields
- **THEN** validation rejects the submission and no checkpoint is written

#### Scenario: Completed items cannot be removed
- **WHEN** a candidate omits an item already persisted in `completed_items`
- **THEN** the tool rejects the candidate without changing the checkpoint

### Requirement: Legacy handoff remains readable without trusted replay

The Loop MUST load legacy checkpoints whose `handoff` value is a string, projecting it into the structured `summary` field. Loading MUST NOT execute or replay text from the legacy handoff, and the next serialization MUST use the structured handoff shape while retaining the public `schema` key.

#### Scenario: Legacy string checkpoint loads
- **WHEN** a valid old checkpoint contains `"handoff": "continue from item"`
- **THEN** it loads with that value as `handoff.summary`, empty structured item lists, and no other field changes

#### Scenario: Legacy handoff is treated as untrusted context
- **WHEN** resume renders a migrated handoff
- **THEN** the prompt marks it as untrusted state and does not interpret it as a goal, permission, budget, recovery instruction, or tool call

### Requirement: Submission recovery is bounded and non-replaying

Required completion submission recovery MUST have a host-enforced finite bound. A recovery attempt MAY request a corrected submission of the current state, but MUST NOT automatically replay any prior tool call or external action. When the bound is exhausted, the task MUST stop with failure rather than retry indefinitely.

#### Scenario: First missing submission gets a recovery prompt
- **WHEN** a task declares completion without the required submission
- **THEN** the host sends one bounded correction prompt and does not dispatch a historical tool call

#### Scenario: Recovery bound is exhausted
- **WHEN** the task again omits or invalidates the required submission after the bound
- **THEN** the task stops as failed and performs no replay

#### Scenario: Unknown external action is not replayed
- **WHEN** a Loop has a pending or unknown external-action receipt during recovery
- **THEN** the Loop stops at the existing receipt safety boundary and requires explicit reconciliation; it does not dispatch the action again

```
