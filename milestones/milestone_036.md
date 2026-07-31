# 里程碑 M36: HTTP 动作审批条件边界

- 状态: 已完成
- 起止: 2026-07-31 ~ 2026-07-31
- 对应 ACTION_PLAN 行: M36
- 前置里程碑: [milestone_035](milestone_035.md)
- OpenSpec change: [document-http-action-approval-trigger](../openspec/changes/archive/2026-07-31-document-http-action-approval-trigger/)

## 目标与范围

本里程碑修正文档边界，不实现运行时能力：

- 两份借鉴清单均登记 HTTP 远程动作审批绑定为条件候选；
- 触发条件是出现外部 HTTP 动作控制面，并能提供将审批绑定到 action digest/scope 的真实 verifier；
- 当前 HTTP 仍是 loopback-only，不新增远程入口、审批 API、receipt 类型、依赖或身份 schema；
- 保留 Memory 迁移、Rewrite/依赖条件门槛；外部分发目标已移除。

## 两轮自评

### 方案自评

- 第一轮：不新增里程碑会继续保留两份文档对 HTTP 审批绑定的范围矛盾；新增运行时则超出当前无远程控制面事实。
- 第二轮：采用文档专项，将其列为条件候选并加入 verifier 门槛，既纠偏又不虚构产品需求。

### 收尾自评

- 条件候选明确写出当前 loopback-only，不会被误读为 HTTP 远程能力已交付。
- Memory 迁移与 Rewrite/依赖仍需真实触发；未修改源码、依赖、Memory 数据或发布 change。
- `publish-v0-1-0` 已撤销归档，保留 4/9 历史任务上下文；不提供恢复路径。

## 验收证据

- `uv run pytest tests/test_borrowing_roadmap.py tests/test_governance_docs.py -q` -> `10 passed`。
- `uv run ruff check .` -> 通过。
- `uv run ruff format --check .` -> `126 files already formatted`。
- `git diff --check` -> 通过。
- `openspec validate --all --strict --no-interactive` -> `31 passed, 0 failed`。
- 归档后复核：OpenSpec strict `30 passed, 0 failed`；归档目录和主规格均可验证。

## 发布边界

外部分发不在当前路线图；原 `publish-v0-1-0` 已撤销归档。

## 续接指引

M36 完成后，只有在出现具体外部 HTTP 动作控制面、既有 Memory 元数据迁移需求或 Rewrite/依赖瓶颈时，才按 Comet 流程独立立项；没有触发时保持当前基线不变。

## M45 对账注记

- 本文件于 M45 从已验证历史工件恢复；原测试计数只对应当时快照，当前 HEAD 由 M45 全量门禁证明。
- 包索引发布、正式 tag 和发布自动化仍不在路线图；经用户授权的普通开发分支 push 仅用于版本控制交接。
- 当前基线以 `ACTION_PLAN.md` 和 `milestones/latest` 为准，本文件中的旧“续接指引”只保留历史语境。
