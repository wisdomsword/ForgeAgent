# Brainstorm Summary

- Change: external-action-receipts
- Date: 2026-07-30

## 确认的技术方案

- 只覆盖非 `autoApprove` 的 MCP 外部动作；`autoApprove` 继续表示现有只读兼容路径。
- 新增项目内 `ExternalActionReceiptStore`，权威文件位于 `<allowed_root>/.forgeagent/receipts/`，使用严格 schema、脱敏有界字段、符号链接检查、每动作 revision 锁、临时文件原子替换和 `fsync`。
- delivery phase 固定为 `prepared`、`dispatched`、`confirmed`、`unknown`；resolution 独立为 `open`、`confirmed`、`abandoned`、`retry_approved`。未知动作在人工确认后仍保留 `phase=unknown` 历史，不伪装成收到协议响应。
- MCPTool 先复用现有确认门，再创建 prepared；调用 SDK 前转 dispatched；MCPManager 返回内部 `not_dispatched`、`confirmed`、`unknown` certainty；只有协议响应或可证明未调用 SDK 才结束 delivery phase。
- Audit 只写收据迁移的脱敏投影，仍保持 fail-open；pending/replay 判断只读权威 receipt store。
- LoopRunner 在 run 的每次迭代前检查同一 Loop 的 resolution=open 收据，resume 产生的 runner 在真正创建 Task 前再次检查；存在未决收据时以 `external_action_pending` 停止，不创建模型/工具/协作角色。
- CLI 增加 `receipts list` 与 `receipts resolve ACTION_ID`；`--confirmed`、`--abandon`、`--retry` 互斥，confirmed 需要 bounded evidence；resolve 只改变决策，不执行原动作。
- CLI/HTTP/协作入口注入同一 receipt store；无 MCP Task 保持原行为。未注入 store 的受保护 MCP 直接 fail closed，自动批准路径不受影响。

## 关键取舍与风险

- `confirmed` 代表 MCP 协议层已获得响应或确认未 dispatch，不代表业务系统已完成预期语义；协议错误保存为 `remote_ok=false`。
- `prepared` 与 `dispatched` 在崩溃后都视为未决；只有 manager 能证明 SDK session 未开始才可标记 no-dispatch。
- 超时/取消/异常在 dispatch 后统一视为 `unknown`，不根据异常类型猜测远端结果。
- `retry_approved` 只允许未来显式调用生成新 action ID；原收据保持历史，系统不自动重放。
- 只把 HTTP/CLI 的装配改为共享 store，不新增 HTTP reconciliation API，避免把本里程碑扩展成跨入口控制面。

## 测试策略

- 收据模型/存储：状态迁移、原子写、锁、stale revision、symlink/path replacement、畸形/超限/secret masking。
- MCP：拒绝、autoApprove、confirmed protocol error、no-dispatch、timeout/cancel/exception unknown、旧 `ok/text` 兼容和 audit degraded。
- Loop：resume/pre-iteration pending gate、reconciled continuation、新 action ID、无 receipt 回归。
- CLI：list/resolve 互斥参数、evidence bounds、脱敏、stale revision、无自动 dispatch。
- 完成前执行专项测试、全量 pytest、Ruff、build、OpenSpec strict，并做两轮独立一致性/安全自评审。

## Spec Patch

无。当前 delta specs 已覆盖本设计；若实现中出现中等范围接口变化，按 Comet build 规则先暂停并更新 spec/design。
