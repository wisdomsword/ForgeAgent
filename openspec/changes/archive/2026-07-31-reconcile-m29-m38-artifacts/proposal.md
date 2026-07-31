## Why

当前 M44/M45 Git 基线包含 M29-M38 的运行时实现与后续里程碑，却缺少 8 份里程碑记录、10 个已归档 change、关联设计/计划/验证报告和 4 个主规格；多个既有主规格还保留归档器生成的 `Purpose: TBD`。这会让 `milestones/latest`、ACTION_PLAN、OpenSpec 与真实代码形成不可审计的断链。

## What Changes

- 建立逐项来源清单，只从主工作区恢复可由 `archived: true`、`verify_result: pass`、归档 delta 和现有实现共同证明的 M29-M38 工件。
- 恢复 `milestone_029` 至 `milestone_032`、`milestone_035` 至 `milestone_038`，以及它们缺失的归档 change 和 Superpowers design/plan/report。
- 恢复 `agent-governance-gates`、`attention-state-protocol`、`runtime-skill-exit-contract`、`structured-collaboration-handoff` 主规格，并恢复 M34 对 `skills-runtime` 的 governed exit-contract 要求。
- 保留当前 M44 借鉴清单、HTTP action approval、M45 MCP 修复规格和 `milestones/latest`，禁止旧工件覆盖新基线。
- 为所有主规格填写准确 Purpose，增加离线契约测试，禁止归档器 `TBD`、缺失里程碑链、未归档状态和已撤销 PyPI 目标重新进入当前规划。
- 为恢复的历史里程碑加 M45 对账注记：历史测试计数不是当前 HEAD 证明；开发分支 push 与已移除的包发布/tag/发布自动化目标相互独立。

## Capabilities

### New Capabilities

- `repository-lifecycle-integrity`: 定义里程碑、归档 change、设计/计划/报告、主规格和当前基线之间的可验证完整性。
- `agent-governance-gates`: 恢复 M32 已交付的 Prompt/Skill、Memory 与 Rewrite/依赖开发期治理规格。
- `attention-state-protocol`: 恢复 M29 已交付的注意力状态与终态分离规格。
- `runtime-skill-exit-contract`: 恢复 M34 已交付的版本化 Skill 退出契约规格。
- `structured-collaboration-handoff`: 恢复 M31 已交付的 host-owned 结构化协作交接规格。

### Modified Capabilities

- `skills-runtime`: 恢复 M34 已实现的 version 2 exit contract、fail-closed discovery 与按需 `exit_conditions` 读取要求。

## Impact

- 文档与证据：`milestones/`、`docs/superpowers/`、`docs/agent-governance-gates.md` 和一份 M45 对账报告。
- OpenSpec：恢复历史 archive，补齐 4 个主规格、`skills-runtime` 已实现增量和所有主规格 Purpose。
- 测试：增加只读、离线的仓库生命周期契约测试；复用现有 governance/borrowing/skills/attention/collaboration 回归。
- 运行时：不新增行为、不修改公开 API、不迁移数据、不新增依赖。
- 分发：不恢复 PyPI、正式 tag 或发布自动化；本 change 内不 push。
