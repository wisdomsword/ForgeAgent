## Why

M45 完成运行时、历史工件和 verifier 对账后，`milestones/latest` 已切换到 M45，但两份借鉴评审文档和 canonical `borrowing-review-baseline` 仍把 M44 写死为当前基线。继续保留会让规划入口与仓库事实不一致；仅机械替换成 M45 又会在下一个里程碑重复失效。

## What Changes

- 将借鉴评审文档的当前基线同步为 M45，并保留 M44 HTTP 动作审批和 M43 Rewrite 测量的历史证据。
- 将规划基线规范改为跟随 `milestones/latest`，不再永久写死某个里程碑编号。
- 增强生命周期测试，要求 frontmatter、正文和 latest 指针一致，同时继续验证已移除的发布目标与开发分支 push 的区别。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `borrowing-review-baseline`：借鉴评审文档必须以 `milestones/latest` 指向的已完成里程碑作为当前基线，并保留各项能力的真实历史交付边界。

## Impact

- 文档：两份 Agent 开发指南借鉴评审文档、M45 里程碑记录。
- 测试：`tests/test_borrowing_roadmap.py`、`tests/test_repository_lifecycle.py`。
- 不修改运行时代码、公开 API、依赖、HTTP listener、发布目标或数据格式。
