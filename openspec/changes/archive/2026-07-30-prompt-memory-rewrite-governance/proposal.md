# Prompt、Memory 与重写治理门禁

## Why

评审已确认 Prompt/Skill 退出条件、Memory 四问和 Rewrite/依赖门禁是可借鉴的流程纪律，但当前项目只有分散的原则描述，没有一份可执行、可回归检查的入口。继续迭代时容易出现提示词没有停止证明、长期记忆缺少来源与失效策略，或重写/引入依赖没有基线和回滚证据的问题。

## What Changes

- 新增一份项目级治理门禁，规定每条新增或修改的长期 Prompt/Skill 必须声明成功、失败、阻塞、需输入和超时/预算退出条件。
- 将 Memory 四问固化为写入长期记忆前必须填写的评审字段：为什么记、什么是真相、何时失效、谁可见以及如何删除/更正。
- 将 Rewrite/依赖门禁固化为变更评审模板，要求提供性能、可靠性、维护成本、兼容性、团队能力和迁移/回滚成本的基线、门槛与证据。
- 增加文档契约测试，检查门禁章节、字段和关键反例不会被后续规划文档删除或改成不可验收的绝对承诺。
- 不改变 Skill、Memory、Prompt 的运行时数据格式或行为，不迁移既有 `MEMORY.md`，不新增依赖。

## Capabilities

### New Capabilities

- `agent-governance-gates`: 为长期 Prompt/Skill、长期 Memory 和大规模重写/依赖变更提供可验证的项目级流程门禁。

### Modified Capabilities

无。现有运行时能力不改变；本 change 只新增开发期治理契约和其文档回归检查。

## Impact

- 文档：`spec.md`、`MILESTONE_GUIDE.md`、`ACTION_PLAN.md`、`docs/reviews/2026-07-30-agent开发指南评审-综合借鉴清单与任务开发流程.md`、`docs/threat-model.md`。
- 测试：新增治理文档契约测试，不调用网络、不需要模型凭据。
- OpenSpec/Comet：新增独立 change 和归档能力规格。
- 发布：PyPI 上传、正式 tag、远程 push 与 `publish-v0-1-0` 均不在范围内，继续暂停。
