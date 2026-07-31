# 里程碑 M38: 移除外部分发目标并退役发布 change

## 状态

- 状态: 已完成
- 起止: 2026-07-31 ~ 2026-07-31
- 对应 ACTION_PLAN 行: M38
- 前置里程碑: [milestone_037](milestone_037.md)
- OpenSpec change: [retire-pypi-publication-goal](../openspec/changes/archive/2026-07-31-retire-pypi-publication-goal/)

## 目标与范围

- 重新评审 M30 及之后的里程碑、ACTION_PLAN、借鉴清单、治理规范、RC 文档和 active OpenSpec 状态。
- 将包索引发布、正式版本 tag、远程 push 和发布自动化从当前路线图移除。
- 保留 M28 RC 的历史工程验证事实，不把它改写为公开发布。
- 将原 `publish-v0-1-0` 的未完成任务标记为取消/不适用，移动到带撤销说明的日期归档目录。
- 不修改运行时代码、依赖、API、Memory 数据或外部分发系统。

## 两轮自评

### 方案自评

- 第一轮确认：M30-M37 核心能力证据本身没有需要重做的缺口，主要问题是“发布暂停”被重复写成未来目标。
- 第二轮确认：历史事实与当前路线图必须分离；保留 RC 未发布事实、移除恢复授权语义、撤销 active change 是最小且可追溯的方案。

### 收尾自评

- active `publish-v0-1-0` 目录已不存在；原 proposal/design/tasks/specs 与撤销说明均位于日期归档目录。
- canonical 治理文档、借鉴清单、RC 说明、ACTION_PLAN 和 M30-M37 里程碑均声明分发目标已移除。
- 离线专项测试、OpenSpec strict、Ruff 和 diff 检查均通过；未执行上传、tag、push 或网络操作。

## 验收证据

- `uv run pytest tests/test_m28_release_docs.py tests/test_borrowing_roadmap.py tests/test_governance_docs.py -q` -> `16 passed`。
- `uv run pytest` -> `2480 passed, 10 skipped`。
- `openspec validate --all --strict --no-interactive` -> `29 passed, 0 failed`（归档后）。
- `uv run ruff check .` -> `All checks passed!`。
- `uv run ruff format --check .` -> `126 files already formatted`。
- `git diff --check` -> 通过。

## 分发边界

包索引发布、正式版本 tag、远程 push 和发布自动化已移出当前路线图。未来若重新考虑公开分发，必须建立全新的独立 change；本里程碑和已撤销 change 不提供恢复路径。

## 续接指引

读取 `milestones/latest` 和 `ACTION_PLAN.md`。当前没有已授权的发布目标；后续只在真实需求触发时，为 Memory 迁移、Rewrite/依赖或 HTTP 远程动作审批绑定建立独立 change。

## M45 对账注记

- 本文件于 M45 从已验证历史工件恢复；原测试计数只对应当时快照，当前 HEAD 由 M45 全量门禁证明。
- 包索引发布、正式 tag 和发布自动化仍不在路线图；经用户授权的普通开发分支 push 仅用于版本控制交接。
- 当前基线以 `ACTION_PLAN.md` 和 `milestones/latest` 为准，本文件中的旧“续接指引”只保留历史语境。
