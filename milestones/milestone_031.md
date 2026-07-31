# 里程碑 M31: Duo/Triad 结构化协作交接

- 状态: 已完成
- 起止: 2026-07-30 ~ 2026-07-30
- 对应 ACTION_PLAN 行: M31（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_030](milestone_030.md)
- 技术设计: [2026-07-30-structured-collaboration-handoff-design](../docs/superpowers/specs/2026-07-30-structured-collaboration-handoff-design.md)
- 实施计划: [2026-07-30-structured-collaboration-handoff](../docs/superpowers/plans/2026-07-30-structured-collaboration-handoff.md)
- OpenSpec change: [2026-07-30-structured-collaboration-handoff](../openspec/changes/archive/2026-07-30-structured-collaboration-handoff/)
- 验证报告: [2026-07-30-structured-collaboration-handoff-verify](../docs/superpowers/reports/2026-07-30-structured-collaboration-handoff-verify.md)

## 目标与范围

在现有 Duo/Triad 串行角色边界增加结构化、冻结、有界、可恢复重建的 host-owned
handoff。范围不含调度器、租约、网络控制转移、数据库、自动收据 resolve/replay、
新依赖、发布或 PyPI。

## 方案设计

- `HandoffPacket` 从 `CollaborationState`、角色 registry、checks 和已有宿主 receipt store
  生成，不是模型自由摘要，也不是新的状态权威。
- Planner→Generator、Generator→Evaluator、Evaluator→caller 的 return owner 固定；Duo
  跳过 Planner，Single 不创建 packet。
- 收据只投影 server/tool label、phase、dispatch certainty；缺少绑定上下文、存储或查询
  失败时明确 `unavailable`，不宣称“没有未决副作用”。
- 过程中的两轮方案自评：第一轮确认最小范围和状态所有权；第二轮确认 attempt/digest、
  收据可见性、能力摘要、旧字段兼容和发布暂停边界。

## 子任务清单

- [x] 增加严格冻结 `HandoffPacket`、能力/审批、checkpoint、公开收据投影和稳定 digest
- [x] 将 packet/digest 注入 Planner、Generator、Evaluator 任务数据并保留 `loop_context`
- [x] 发出有界 `collaboration.handoff` 审计事件，完成 Duo/Triad/rejection/resume 回归
- [x] 更新协作协议、HTTP 文档和 threat model
- [x] 完成全量验证、两轮最终自评和 OpenSpec/Comet 归档

## 交付物清单

- [x] `src/forgeagent/collaboration.py` — handoff contract, builder, digest, receipt/capability projection
- [x] `src/forgeagent/cli.py` — Loop/HTTP 宿主传递已有 receipt store
- [x] `tests/test_collaboration_handoff.py` — strict/masking/digest/receipt/audit coverage
- [x] `tests/test_collaboration_runner.py`、`tests/test_collaboration_integrations.py` — role/resume/compatibility regression
- [x] `docs/threat-model.md`、`docs/text-protocol-spec.md`、`docs/http-task-service.md`
- [x] OpenSpec archived change、Superpowers design/plan/report

## 三次评审

### 技术方案评审

- [x] 两轮方案自评确认方案只增加宿主投影，不改变状态所有权、提交门或恢复语义
- [x] 交接字段覆盖目标/范围、事实、假设、未决副作用、能力/审批、checkpoint、停止条件和返回归属
- [x] 未引入调度器、租约、网络控制转移、自动重放或 PyPI 行为

### 代码评审

- [x] 主 Agent 两轮逐文件自审：检查 attempt/digest、role capability、receipt visibility、secret/path masking 和 CLI 构造点
- [x] 发现问题已修复：attempt 纳入 packet/digest；无 task/loop 绑定时 receipt store 显式降级 unavailable；Evaluator 只读能力投影不误标提交工具
- [x] 独立 reviewer 在本会话不可用；以专项/全量回归、Ruff、OpenSpec 和两轮主 Agent 自评作为代码评审证据

### 验收评审

- [x] 专项与 CLI/Loop 回归：`379 passed`
- [x] 完整回归：`2456 passed, 10 skipped`
- [x] `uv run ruff check .`、`uv run ruff format --check .`、`git diff --check` 通过
- [x] `uv build` 通过，生成 `dist/forgeagent-0.1.0.tar.gz` 与 `dist/forgeagent-0.1.0-py3-none-any.whl`
- [x] `openspec validate --all --strict --no-interactive`：`27 passed, 0 failed`
- [x] 未执行外部分发；原 `publish-v0-1-0` 后续已撤销并归档

## 遗留问题

- [x] 正式外部分发目标已移除 — 影响：保留本地/RC 工程证据，不产生公开发布证据 — 处理：原发布 change 已撤销并归档，无恢复路径
- [ ] receipt status 仍是只读公共投影 — 影响：不替代外部动作恢复协议 — 计划：继续由现有 receipt store/Loop 策略处理

## 续接指引

M31 已完成实现、验证和 Comet/OpenSpec 归档。`milestones/latest` 指向本文件；下一阶段应
先读取本文件和 ACTION_PLAN，继续按综合借鉴清单的下一候选单独建立 change。保持当前分支
未自动提交的用户脏工作区；外部分发不在当前路线图，原 `publish-v0-1-0` 已撤销归档。

## M45 对账注记

- 本文件于 M45 从已验证历史工件恢复；原测试计数只对应当时快照，当前 HEAD 由 M45 全量门禁证明。
- 包索引发布、正式 tag 和发布自动化仍不在路线图；经用户授权的普通开发分支 push 仅用于版本控制交接。
- 当前基线以 `ACTION_PLAN.md` 和 `milestones/latest` 为准，本文件中的旧“续接指引”只保留历史语境。
