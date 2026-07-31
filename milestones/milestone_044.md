# 里程碑 M44: HTTP 动作审批绑定

- 状态: 已完成并归档
- 起止: 2026-07-31 ~ 2026-08-01
- 对应 ACTION_PLAN 行: M44（见该文件 §四里程碑表）
- 前置里程碑: [milestone_043](milestone_043.md)
- OpenSpec change: [bind-http-remote-action-approvals](../openspec/changes/archive/2026-07-31-bind-http-remote-action-approvals/)
- 分发边界: 不执行 PyPI、tag 或发布自动化；普通开发分支 push 已获明确授权，仅作版本控制交接

## 目标与范围

M44 在既有 loopback-only + Bearer HTTP 控制面内增加真实动作审批绑定：每个 `allow_once` 权限精确绑定
task、MCP scope、canonical request digest 和 1-3600 秒有效期；任务发布前原子认领，dispatch 前持久化
receipt，一次消费后不可恢复。HTTP 只提供显式、revision-guarded 的 receipt reconcile，不自动调用 MCP、
恢复任务或重放未知动作。

本里程碑不开放非 loopback listener，不引入 Gateway、远程部署、分布式权限存储、新依赖或 exactly-once
承诺。未消费审批保持 process-local，进程重启后必须重新签发；durable open receipt 可凭 exact task ID
继续显式恢复。

## 方案设计

- `HttpActionApprovalStore` 使用严格冻结模型、单锁状态迁移、有界容量与固定安全错误；`bind_many` 全有或全无。
- `HeadlessConfirmer` 保持静态 allowlist 优先，仅在未命中时消费当前任务精确 scope/digest 权限。
- `TaskService` 在 worker 发布前绑定审批，终态、取消、拒绝和 shutdown 均关闭未消费权限。
- receipt route 优先验证 retained task；重启后只有 exact task-owned durable open receipt 建立窄化恢复权限。
- HTTP 公开面和 audit 不输出 goal、raw arguments、secret、绝对路径、evidence 正文或 raw exception。
- 技术设计见 `docs/superpowers/specs/2026-08-01-http-remote-action-approval-binding-design.md`。

## 子任务清单

- [x] 实现有界审批状态机、严格字段和一次性消费。
- [x] 接入 MCP 确认门与 TaskService 原子任务绑定/生命周期清理。
- [x] 增加审批和 receipt HTTP 路由，保持认证、body 与固定错误边界。
- [x] 完成真实 loopback verifier、两轮自评审和重启后 durable receipt 恢复。
- [x] 修复隔离分支遗漏的 M33/M34、attention 和审计测试基线。
- [x] 完成 full verify、主规格同步和 Comet/OpenSpec 归档。

## 交付物清单

- [x] `src/forgeagent/http_action_approvals.py` — process-local、bounded、allow-once 权限权威。
- [x] `src/forgeagent/headless.py`、`src/forgeagent/http_task_service.py` — 动态消费与任务生命周期绑定。
- [x] `src/forgeagent/http_server.py`、`src/forgeagent/_cli_http.py` — 认证控制路由与共享权威组装。
- [x] `src/forgeagent/external_actions.py`、`src/forgeagent/tools.py` — receipt 安全投影和固定审计标签。
- [x] `scripts/m44_http_action_approval_smoke.py` — 真实 loopback 审批、dispatch 和 reconcile verifier。
- [x] `tests/test_http_action_approvals.py` 及 HTTP/Task/CLI/Tool 测试 — 状态、竞态、恢复和泄漏边界。
- [x] `docs/superpowers/reports/2026-08-01-bind-http-remote-action-approvals-verify.md` — 完整验证报告。
- [x] `openspec/changes/archive/2026-07-31-bind-http-remote-action-approvals/` — 已同步并归档的 change。

## 三次评审

### 技术方案评审

- [x] 保持 loopback-only；审批绑定与 listener 外部暴露是两个独立边界。
- [x] 权限只绑定 MCP action，不扩展为通用远程命令或 Gateway。
- [x] unknown 恢复只改变 receipt resolution，禁止无条件重放。

### 代码评审

- [x] 第一轮自评修复 Loop/Collaboration receipt store 注入、expiry audit 和历史 label 路径泄漏。
- [x] 第二轮从 21 个 scenario 反查，修复进程重启后 durable receipt 被 process-local task gate 阻断的问题。
- [x] 最终一致性复核修正 M33/M34 基线遗漏和“已交付审批绑定仍列为未来候选”的规划漂移。
- [x] 当前会话规则未授权子代理；按用户要求执行两轮独立视角自评审，未伪造 code-reviewer 结论。

### 验收评审

- [x] 聚焦门禁 `572 passed`；最终全量 `2695 passed, 10 skipped`。
- [x] Ruff、144 文件 format、`uv build`、diff check 和 OpenSpec strict `29/29` 通过。
- [x] 真实 verifier：`dispatch_count=1`、`reconcile_dispatch_delta=0`、approval consumed、unknown 显式 confirmed。
- [x] 6/6 requirements、21/21 scenarios 完成；Comet archive `7/7 steps succeeded`。

## 遗留问题

M44 无未完成任务。公网 listener、Gateway 与跨主机部署仍未授权；若出现真实跨主机需求，必须另立
change，复用 M44 权限状态机并新增部署级鉴权、网络边界、撤销和真实环境 verifier。审批进程重启丢失、
receipt 不能证明远端业务 exactly-once 均是已声明边界，不是本里程碑遗漏。

## 续接指引

M44 已完成实现、全量验证、主规格同步和归档。后续 HTTP 仍绑定 loopback；不得从“remote action approval”
名称推断公网入口已经开放。若没有新的真实越阈 Rewrite 指标或跨主机 HTTP 需求，不应继续扩建平台层。
PyPI、正式 tag 和发布自动化继续保持移除；普通开发分支 push 仅按明确授权执行。
