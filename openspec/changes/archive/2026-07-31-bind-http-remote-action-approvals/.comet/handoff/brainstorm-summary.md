# Brainstorm Summary

- Change: bind-http-remote-action-approvals
- Date: 2026-08-01

## 确认的技术方案

采用独立的进程内 `HttpActionApprovalStore` 与既有持久化 `ExternalActionReceiptStore`。HTTP 调用者先签发精确 MCP scope/digest 的短期 `allow_once` 审批，任务提交以 approval ID 列表全有或全无认领；`HeadlessConfirmer` 只为当前 task 原子消费完全匹配的审批。新增 task-scoped receipt list/resolve 路由，所有 resolve 都只是 CAS 状态更新，不 dispatch、不自动 resume。

## 关键取舍与风险

- 监听继续 loopback-only，不引入 Gateway/TLS/多租户认证。
- 审批进程内且短期；重启后重新签发，receipt 持久事实不丢失。
- 客户端必须预计算 canonical digest；拒绝 wildcard 和原始 arguments 持久化。
- consume 与 revoke 由同一锁确定顺序；消费后 receipt 写失败也不返还额度。
- 普通任务不支持运行后自动重跑；Loop 恢复仍需显式 resume 和新审批。
- 干净 HEAD 缺失 attention 模块，作为最小基线前置修复纳入任务。

## 测试策略

状态机、HeadlessConfirmer、TaskService、HTTP parser/routes 分层 RED/GREEN；覆盖错 task/scope/digest、过期、重复消费、撤销竞态、部分认领回滚、调度/取消/shutdown 清理、跨任务 receipt、stale revision 和无 replay。最终用真实 loopback socket + MockClient + fake MCP 完成端到端 verifier，并执行全量 pytest、Ruff、format 和 OpenSpec strict。

## Spec Patch

无。
