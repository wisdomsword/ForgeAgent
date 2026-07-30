## 1. 收据模型与耐久存储

- [x] 1.1 增加严格收据模型、四种 delivery phase、独立 resolution 字段、有界脱敏/转义和稳定 schema 校验。
- [x] 1.2 实现符号链接安全、allowed-root 约束、原子替换、每动作 revision 锁、list/load/pending 查询和畸形记录 fail-closed 的收据存储。
- [x] 1.3 增加 create/transition/reconcile、中断后的中间状态、stale revision、畸形文件、路径替换、字段边界和 secret masking 的专项测试。

## 2. MCP dispatch 集成

- [x] 2.1 扩展 MCP 内部结果，区分 `not_dispatched`、`confirmed`、`unknown`，保留现有 `ok/text` 和脱敏错误语义。
- [x] 2.2 让非 auto-approved MCP 调用经过 prepared/dispatched/confirmed-or-unknown 收据迁移；保持现有确认门、HTTP allowlist 和只读自动批准路径。
- [x] 2.3 返回固定 result-unknown 反馈，增加收据迁移 audit 投影，并测试拒绝、预批准、协议错误、超时/取消、不可用 session 和 audit degraded 路径。

## 3. Loop 与入口恢复 gate

- [x] 3.1 在 Loop resume 和迭代前加入未决收据检查，使用稳定的 `external_action_pending` 停止语义；阻断时不得创建 Task 或模型调用。
- [x] 3.2 在 CLI、HTTP 和 collaboration Task 装配中传递 receipt store、Task/Loop 关联，不改变无 MCP Task 行为。
- [x] 3.3 增加 resume 阻断、下一迭代阻断、reconciliation 后继续、新动作 ID 和普通无收据 Loop 的确定性测试。

## 4. 显式 reconciliation 接口

- [x] 4.1 增加有界的 `forgeagent receipts list` 和 `forgeagent receipts resolve` CLI 命令，要求互斥决策并校验证据。
- [x] 4.2 增加列举、确认、放弃、重试授权、stale revision、脱敏和不自动 dispatch 的 CLI 测试。

## 5. 文档与验证

- [x] 5.1 更新威胁模型、MCP/Loop 用户文档和与发布无关的能力说明，明确 unknown 状态和禁止重放契约。
- [x] 5.2 执行专项测试、全量 pytest、Ruff、构建、OpenSpec strict 校验和两轮自评审；记录残余限制，不恢复 PyPI 发布。
