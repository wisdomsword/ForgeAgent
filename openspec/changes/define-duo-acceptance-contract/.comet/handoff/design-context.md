# Comet Design Handoff

- Change: define-duo-acceptance-contract
- Phase: design
- Mode: compact
- Context hash: 2250e4268f6a8e118d3cf305511001e6f918fcb215a26183547b315c77a91f8e

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/define-duo-acceptance-contract/proposal.md

- Source: openspec/changes/define-duo-acceptance-contract/proposal.md
- Lines: 1-25
- SHA256: 0c6bd1e7773f92a0ced71112a7a9300b356176620ee7d1cf3b20067437dc3f9e

```md
## Why

Duo 当前把任意 goal 固定成“原始目标已满足”，Evaluator 无法从该验收项知道应观察什么证据。M39 需要在不引入 LLM 拆解器或新依赖的前提下，让默认 Duo 计划成为确定、可冻结、可直接检查的验收契约。

## What Changes

- `_duo_plan(goal)` 根据 goal 的可观察交付形态选择固定验收模板，而不再丢弃入参。
- 保持单个稳定计划项 ID，避免破坏既有持久化状态和 SubmitEvaluation 覆盖契约。
- 文件/产物、命令/验证、文本/分析三类 goal 分别得到可由 Evaluator 直接观察的 behavior 与 acceptance。
- 禁止“原始目标已满足”“满足用户需求”等循环论证式伪验收。
- 增加至少三个 Duo golden case，覆盖三类交付形态和路径/secret 不泄漏边界。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `runtime-collaboration`：Duo 默认验收计划必须由 goal 的交付形态确定性生成，并包含可直接观察的证据契约。

## Impact

影响 `src/forgeagent/collaboration.py`、Duo store/runner 测试与协作规范。不改变 Triad Planner，不新增依赖、LLM 调用、配置项或发布动作。

```

## openspec/changes/define-duo-acceptance-contract/design.md

- Source: openspec/changes/define-duo-acceptance-contract/design.md
- Lines: 1-38
- SHA256: 643335765dc2a6536b8e251c862b4e5d23b65ac17829abd01f2fef25fa1a5bb1

```md
## Context

Duo 没有 Planner，必须由宿主生成冻结计划。当前实现保留一个 `goal` 计划项，但 behavior/acceptance 是不可观察的同义反复。大量持久化、恢复和评估测试依赖稳定 item ID，因此本 change 应改进内容契约而非扩大计划形状。

## Goals / Non-Goals

**Goals：**

- 使用纯确定性、无依赖逻辑把 goal 归入产物、验证或文本结果三类。
- 每类返回一个稳定 `goal` item，验收文本明确 Evaluator 可观察的证据类型。
- 计划正文经过既有 AcceptanceItem 安全校验，不复制原始 goal、绝对路径或 secret。

**Non-Goals：**

- 不使用 LLM 自动拆解 goal。
- 不把一个 goal 拆为多个动态计划项。
- 不改变 Triad Planner、Evaluator 工具权限或 EvaluationItem 结构。

## Decisions

1. **保留单计划项和 `goal` ID。** 这维持旧 snapshot、plan digest/恢复不变量和既有 SubmitEvaluation 兼容。改成三个固定项会让旧 Evaluator 结果缺项，并制造不必要迁移。
2. **使用有限关键词分类而非通用自然语言解析。** 文件/产物信号优先，其次验证/命令信号，最后回退文本/分析结果。规则小、可测试、失败时仍返回可观察的文本结果契约。
3. **模板不嵌入 goal 正文。** Goal 只决定模板类别；behavior/acceptance 使用固定 English-first 文本，避免路径、secret 和 prompt 正文进入计划或报告。
4. **验收要求证据而非主观判断。** 产物类要求相对位置与内容可检查，验证类要求注册检查或有界命令结果，文本类要求可引用的响应片段与支撑证据。

## Risks / Trade-offs

- [风险] 关键词不能覆盖所有自然语言表达。→ 未命中时回退到文本/分析模板，仍比循环论证可观察；不升级为 LLM 拆解。
- [风险] 同时包含文件和测试的 goal 只选一类。→ 产物优先，Evaluator 仍可观察最终交付物；复杂多条件任务应使用 Triad Planner。
- [风险] 计划文本变化会改变新 Duo 状态的 plan digest。→ 旧 snapshot 按持久化计划继续加载；只有新建 Duo 使用新 digest。

## Migration Plan

旧 snapshot 不重算 plan。新建 Duo 使用新模板；回滚只需恢复旧 `_duo_plan` 文本，无磁盘迁移。

## Open Questions

无。M39 已限定不新增依赖和 LLM 拆解器。

```

## openspec/changes/define-duo-acceptance-contract/tasks.md

- Source: openspec/changes/define-duo-acceptance-contract/tasks.md
- Lines: 1-15
- SHA256: 2e7fd5b301459d36b6b10efcc372b151894b17fb7978a9d13ee8e567791fbc68

```md
## 1. Golden contract tests

- [ ] 1.1 为产物、验证和文本/分析 goal 编写至少三个失败的 Duo golden case。
- [ ] 1.2 增加禁止循环验收文案、计划稳定性和不泄漏 goal/path/secret 的回归断言。

## 2. Minimal implementation

- [ ] 2.1 用小型确定性分类器重写 `_duo_plan(goal)`，保持单项 `goal` ID 和冻结 digest 契约。
- [ ] 2.2 保持旧 snapshot 原样恢复，不引入 LLM 拆解器、依赖或配置。

## 3. Verification

- [ ] 3.1 运行 Duo/Collaboration focused pytest、Ruff、format 和 OpenSpec strict。
- [ ] 3.2 运行全量 pytest 与 `uv build`，确认不执行 PyPI、tag、push 或发布自动化。
- [ ] 3.3 完成两轮自评审并记录 verification report。

```

## openspec/changes/define-duo-acceptance-contract/specs/runtime-collaboration/spec.md

- Source: openspec/changes/define-duo-acceptance-contract/specs/runtime-collaboration/spec.md
- Lines: 1-20
- SHA256: 48490ff65c9f2e1af0df8ea3857646cca8ffccbbaf250e9e3bfe0beb9623298c

```md
## ADDED Requirements

### Requirement: Duo 默认计划提供可观察验收契约
ForgeAgent SHALL 为新建 Duo 协作从 goal 的交付形态确定性生成冻结验收计划。计划项 MUST 使用稳定 ID，MUST 描述 Evaluator 可直接观察的产物、验证结果或响应证据，MUST NOT 使用“原始目标已满足”“满足用户需求”或其他以目标自身作为验收证明的循环表述。生成过程 MUST NOT 调用 LLM、安装依赖、复制原始 goal 正文、绝对路径或 secret。

#### Scenario: 文件或产物 goal
- **WHEN** Duo goal 要求创建、修改或处理文件或其他可检查产物
- **THEN** 冻结计划要求 Evaluator 定位允许根目录内的相对产物并检查其存在性和内容

#### Scenario: 命令或验证 goal
- **WHEN** Duo goal 主要要求运行测试、检查、构建或其他可验证命令
- **THEN** 冻结计划要求 Evaluator 检查注册验证结果或有界命令证据及其成功状态

#### Scenario: 文本或分析 goal
- **WHEN** Duo goal 不属于产物或命令验证类别
- **THEN** 冻结计划要求 Evaluator 引用具体响应片段或安全产物，并检查其是否包含可核对的结论与支撑证据

#### Scenario: 旧 Duo snapshot 恢复
- **WHEN** 持久化 Duo snapshot 已包含旧冻结计划和 digest
- **THEN** 系统按 snapshot 原样恢复，不用新模板重算或拒绝旧计划

```
