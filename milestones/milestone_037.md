# 里程碑 M37: 评审清单条件候选摘要一致性

- 状态: 已完成
- 起止: 2026-07-31 ~ 2026-07-31
- 对应 ACTION_PLAN 行: M37
- 前置里程碑: [milestone_036](milestone_036.md)
- OpenSpec change: [align-http-trigger-next-steps](../openspec/changes/archive/2026-07-31-align-http-trigger-next-steps/)

## 目标与范围

修正借鉴清单“下一步”摘要，使其与 M36 综合清单一致：

- 统一列出既有 Memory 元数据迁移、新 Rewrite/依赖变更、HTTP 远程动作审批绑定三类条件候选；
- 保留 HTTP 当前仅 loopback、需要真实 verifier、出现真实触发后另立 change 的门槛；
- 不修改源码、运行时协议、依赖或 Memory 数据；外部分发目标已从路线图移除。

## 两轮自评

### 方案自评

- 第一轮：直接开始新运行时工作没有需求依据；最小文档修正足以消除 M36 后的摘要遗漏。
- 第二轮：只修改借鉴清单下一步和契约测试，避免重复修改已在 M36 固化的详细条件表。

### 收尾自评

- 三类条件候选在综合清单、借鉴清单、测试和本里程碑中一致。
- HTTP 仍明确为 loopback-only；未产生远程控制面或审批 API 的交付暗示。
- 原 `publish-v0-1-0` 已撤销归档，4/9 仅作为历史任务上下文保留；不提供恢复路径。

## 验收证据

- `uv run pytest tests/test_borrowing_roadmap.py tests/test_governance_docs.py -q` -> `11 passed`。
- `uv run ruff check .` -> 通过。
- `uv run ruff format --check .` -> `126 files already formatted`。
- `git diff --check` -> 通过。
- `openspec validate --all --strict --no-interactive` -> `31 passed, 0 failed`。
- 归档后复核 `openspec validate --all --strict --no-interactive` -> `30 passed, 0 failed`。

## 发布边界

外部分发不在当前路线图；原 `publish-v0-1-0` 已撤销归档。

## 续接指引

无真实 Memory 迁移、Rewrite/依赖瓶颈或外部 HTTP 控制面时，保持 M37 规划基线，不虚构下一项运行时开发。

## M45 对账注记

- 本文件于 M45 从已验证历史工件恢复；原测试计数只对应当时快照，当前 HEAD 由 M45 全量门禁证明。
- 包索引发布、正式 tag 和发布自动化仍不在路线图；经用户授权的普通开发分支 push 仅用于版本控制交接。
- 当前基线以 `ACTION_PLAN.md` 和 `milestones/latest` 为准，本文件中的旧“续接指引”只保留历史语境。
