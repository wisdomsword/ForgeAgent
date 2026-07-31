# 里程碑 M35: 评审规划基线同步

- 状态: 已完成
- 起止: 2026-07-31 ~ 2026-07-31
- 对应 ACTION_PLAN 行: M35
- 前置里程碑: [milestone_034](milestone_034.md)
- OpenSpec change: [sync-borrowing-review-m34-baseline](../openspec/changes/archive/2026-07-31-sync-borrowing-review-m34-baseline/)

## 目标与范围

同步两份 Agent 开发指南评审文档，使后续规划使用 M34 作为当前基线：

- `docs/reviews/2026-07-30-agent开发指南评审-借鉴清单.md` 的 `forgeagent_baseline` 更新为 M34；
- 综合借鉴清单更新当前基线、M34 运行时 Skill 交付状态和剩余条件候选；
- 保留 M33 历史追溯、Memory 迁移/Rewrite 条件门槛，并移除外部分发目标；
- 增加离线契约测试，避免未来再次把 M32 或已完成运行时能力误写为当前状态。

本里程碑不修改源码、运行时规格、Memory 数据、依赖或发布 change。

## 两轮自评

### 方案自评

- 第一轮：仅改 frontmatter 会留下正文矛盾，因此同步 Prompt/Skill 条目和后续候选描述。
- 第二轮：不重写整份评审文档，限定为基线、完成状态、剩余候选和冻结边界四类稳定事实。

### 收尾自评

- 两份文档均引用 M34，M32 明确为继承的开发期治理门禁而非当前基线。
- 运行时 Skill 自动拒绝已标记为归档 change 交付；Memory 迁移和 Rewrite/依赖仍未授权。
- `publish-v0-1-0` 已撤销归档；未执行外部分发。

## 验收证据

- `uv run pytest tests/test_borrowing_roadmap.py tests/test_governance_docs.py -q` -> `9 passed`。
- `uv run ruff check .` -> 通过。
- `uv run ruff format --check .` -> 126 files already formatted。
- `git diff --check` -> 通过。
- `openspec validate --all --strict --no-interactive` -> `30 passed, 0 failed`。
- Comet verify/archive 均通过；归档目录为 `openspec/changes/archive/2026-07-31-sync-borrowing-review-m34-baseline/`。

## 发布边界

外部分发不在当前路线图；`publish-v0-1-0` 已撤销归档，不提供恢复路径。

## 续接指引

M35 已完成并归档，`milestones/latest` 更新为本文件。当前没有新的已授权开发 change；下一步只有在出现真实 Memory 迁移或 Rewrite/依赖需求时，按 Comet full/tweak 流程独立立项。

## M45 对账注记

- 本文件于 M45 从已验证历史工件恢复；原测试计数只对应当时快照，当前 HEAD 由 M45 全量门禁证明。
- 包索引发布、正式 tag 和发布自动化仍不在路线图；经用户授权的普通开发分支 push 仅用于版本控制交接。
- 当前基线以 `ACTION_PLAN.md` 和 `milestones/latest` 为准，本文件中的旧“续接指引”只保留历史语境。
