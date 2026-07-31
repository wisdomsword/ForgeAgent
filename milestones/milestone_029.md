# 里程碑 M29: 注意力状态投影

- 状态: 已完成并归档
- 起止: 2026-07-30 ~ 2026-07-30
- 对应 ACTION_PLAN 行: M29（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_028](milestone_028.md)
- 技术设计: [attention-state-projection-design](../docs/superpowers/specs/2026-07-30-attention-state-projection-design.md)
- 实施计划: [attention-state-projection](../docs/superpowers/plans/2026-07-30-attention-state-projection.md)
- OpenSpec change: [2026-07-30-attention-state-projection](../openspec/changes/archive/2026-07-30-attention-state-projection/)
- 验证报告: [attention-state-projection-verify](../docs/superpowers/reports/2026-07-30-attention-state-projection-verify.md)

## 目标与范围

将可行动的注意力状态与执行终态分离：`running`、`needs_input`、`blocked`、`ready`。
保留旧 `needs_info`、`Termination.NEEDS_INFO` 和 `ToolOutcome.needs_info`；Loop 在安全边界
持久化 attention stop；HTTP 只增加有界 `attention` 字段。范围不含自动恢复、等待队列、通知、
调度器、新依赖、发布、tag 或 push。

## 方案设计

- 新增 frozen/forbid 的 `Attention` 模型及统一安全映射，文本做 secret/path masking、控制字符清理和 500 字符上限。
- Task/Step 产生 attention，Loop 使用 `status=stopped` + `needs_input`/`blocked`，未决外部收据 `external_action_pending` 保持更高优先级。
- HTTP `public_view()` 附加 attention，旧 `status`、`reason`、`detail` 保持不变。
- 裁决 M29-1（2026-07-30）：attention 是状态投影而非新终态；暂停不增加连续失败计数，不自动重放外部动作。
- 裁决 M29-2（2026-07-30）：归档前后均保持 PyPI 发布暂停，不创建 tag、不 push。

## 子任务清单

- [x] 完成 Attention 核心契约与 legacy `needs_info` 映射
- [x] 完成 Step/Task attention 传播和安全审计
- [x] 完成 Loop checkpoint/report/resume attention stop
- [x] 完成 HTTP queued/running/needs-input/blocked/ready 附加投影
- [x] 完成文档、OpenSpec 归档和全量门禁

## 交付物清单

- [x] `src/forgeagent/attention.py` — 注意力模型、安全清洗和 reason 映射
- [x] `src/forgeagent/protocol.py`、`step.py`、`task.py`、`tools.py` — 兼容协议与运行时传播
- [x] `src/forgeagent/loop.py` — 持久化状态、停止不变量和恢复投影
- [x] `src/forgeagent/http_task_service.py` — 安全 HTTP snapshot attention 字段
- [x] `tests/test_attention.py` 及 Step/Task/Loop/HTTP 回归 — 核心状态与边界覆盖
- [x] `docs/http-task-service.md`、`docs/text-protocol-spec.md`、`docs/threat-model.md` — 语义与边界同步
- [x] `docs/superpowers/reports/2026-07-30-attention-state-projection-verify.md` — 验证证据

## 三次评审

### 技术方案评审

- [x] 对照 proposal、design、三份 delta spec 和实施计划，接口与范围一致
- [x] 未新增 endpoint、scheduler、等待队列、自动恢复或依赖
- [x] `external_action_pending` 优先级、legacy `needs_info` 和发布暂停均保持

### 代码评审

- [x] 两轮逐文件自审：检查状态所有权、兼容性、恢复、不变量和公开字段安全边界
- [x] 发现问题已修复：控制字符清洗误插空格；旧 checkpoint attention 默认迁移；attention stop 不计连续失败
- [ ] 未委派独立 code-reviewer — 当前工作区无可用 reviewer agent；以两轮自审和全量回归替代并记录

### 验收评审

- [x] 专项验证：`344 passed`
- [x] 完整回归：`2447 passed, 10 skipped`
- [x] `uv run ruff check .`、`uv run ruff format --check .`、`git diff --check` 通过
- [x] `uv build` 通过；`openspec validate --all --strict --no-interactive` 为 `25 passed, 0 failed`
- [x] PyPI 发布、tag、push 和 `publish-v0-1-0` 均未执行

## 遗留问题

- [ ] 正式 PyPI 发布未执行 — 影响：无正式版本发布证据 — 计划：保持暂停，待另行授权并重新走发布 change

## 续接指引

M29 已完成 Comet verify/archive，attention-state delta 已同步主规格。当前分支仍有本里程碑实现与
用户既有未跟踪文件，均未自动提交；发布 change 继续保持未执行。下一阶段应从本文件和
`milestones/latest` 读取状态，再按新的规划候选单独建立 Comet change，不把候选清单直接当作执行令。

## M45 对账注记

- 本文件于 M45 从已验证历史工件恢复；原测试计数只对应当时快照，当前 HEAD 由 M45 全量门禁证明。
- 包索引发布、正式 tag 和发布自动化仍不在路线图；经用户授权的普通开发分支 push 仅用于版本控制交接。
- 当前基线以 `ACTION_PLAN.md` 和 `milestones/latest` 为准，本文件中的旧“续接指引”只保留历史语境。
