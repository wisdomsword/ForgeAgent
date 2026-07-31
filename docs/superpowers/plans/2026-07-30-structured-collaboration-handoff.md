---
change: structured-collaboration-handoff
design-doc: docs/superpowers/specs/2026-07-30-structured-collaboration-handoff-design.md
base-ref: 6a304bc6273a3acfd06aae81dd265ce3eeef6347
archived-with: 2026-07-30-structured-collaboration-handoff
---

# 结构化协作交接实施计划

> 使用 TDD：每个行为先写失败测试并确认 RED，再实现最小代码，最后运行专项验证。

## 约束

- 不修改或推进 `openspec/changes/publish-v0-1-0`；不上传 PyPI、不创建正式 tag、不 push。
- 保留 M29、M30 及用户已有脏工作区改动，不做无关重构。
- 不新增依赖、endpoint、数据库、调度器、租约管理器或跨进程控制转移。
- packet 只做宿主状态的有界投影；不授权工具调用，不自动处理副作用收据。

## Task 1: 交接契约与投影

**Files:** `src/forgeagent/collaboration.py`, `tests/test_collaboration_handoff.py`, `tests/test_collaboration_models.py`

- [x] 写失败测试：严格冻结 `HandoffPacket`、检查点、能力/审批和收据公共投影拒绝额外字段、控制字符、绝对路径和超长值。
- [x] 写失败测试：相同 durable state 和角色输入生成相同 packet digest；不同 revision/attempt 或拒绝结果生成不同 digest。
- [x] 实现 packet 模型、稳定摘要和基于宿主状态的 packet builder；无 receipt store 或无绑定上下文时明确 `unavailable`。
- [x] 写失败测试：receipt projection 只含公开标签/阶段/dispatch certainty，不包含 action id、参数、凭据或原始错误。

## Task 2: 角色边界与审计

**Files:** `src/forgeagent/collaboration.py`, `tests/test_collaboration_runner.py`, `tests/test_collaboration_integrations.py`

- [x] 将 packet/digest 注入 Planner、Generator、Evaluator 任务数据，保留已有字段和不可信 `loop_context` 兼容语义。
- [x] 在每次角色调用前发出有界 `collaboration.handoff` 事件；不写入目标、事实正文、路径、receipt ID 或凭据。
- [x] 覆盖 Duo、Triad、拒绝后新 Generator、Evaluator→Generator 恢复以及 loop checkpoint 恢复重建。
- [x] 覆盖 Single 模式、旧任务数据兼容和 receipt store 缺失/查询失败回退。

## Task 3: 安全、文档与验证

**Files:** `docs/threat-model.md`, `docs/runtime-collaboration.md`, `openspec/changes/structured-collaboration-handoff/tasks.md`

- [x] 增加 handoff packet 注入、陈旧 packet、收据不可用和权限投影的威胁模型与缓解措施。
- [x] 更新协作运行文档，明确 return owner、恢复重建和“不可用不等于无未决副作用”。
- [x] 运行专项测试、全量 pytest、Ruff check、Ruff format check、`uv build` 和 OpenSpec strict。
- [x] 最终进行两轮自评：检查模糊、错误、过度保守、前后不一致、遗漏和 secret 泄露；发现问题立即修复并重跑验证。

## Task 4: M31 收尾

**Files:** `docs/superpowers/reports/2026-07-30-structured-collaboration-handoff-verify.md`, `ACTION_PLAN.md`, `milestones/milestone_031.md`, `milestones/latest`

- [x] 记录真实验证输出、代码评审结论和遗留边界。
- [x] 更新 M31 计划与 milestone 续接指引；保持 PyPI 发布暂停。
- [x] 仅在验证通过后归档本 change；不触碰 `publish-v0-1-0`。

