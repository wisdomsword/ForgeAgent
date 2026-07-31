## 1. 基线与协议状态机

- [x] 1.1 补入已被现有模块引用的 `attention.py` 和契约测试，并恢复已提交 Skill v2 测试缺失的实现，重跑 M44 聚焦基线并记录原始缺失原因。
- [ ] 1.2 以 RED/GREEN 测试实现有界 `HttpActionApprovalStore`，覆盖严格字段、全有或全无任务绑定、一次性消费、过期、撤销竞态、容量和安全公开投影。

## 2. 执行边界接入

- [ ] 2.1 以测试证明 `HeadlessConfirmer` 只在静态 allowlist 未命中时消费当前任务精确匹配的 MCP scope/digest 审批，且拒绝错 task/scope/digest、过期和复用。
- [ ] 2.2 让 `TaskService` 在 worker 发布前认领审批，并在拒绝、调度失败、取消、终态和 shutdown 时关闭未消费绑定，不把审批 ID 传给模型或普通 options。

## 3. HTTP 控制面与 receipt 恢复

- [ ] 3.1 增加严格认证的审批签发、查询、撤销路由和任务 `approval_ids` 解析，保持旧请求/错误/loopback-only 契约。
- [ ] 3.2 增加按 retained task 列出 open receipts 和 CAS reconcile 路由，覆盖跨任务、stale revision、evidence、无自动 dispatch 与固定错误。
- [ ] 3.3 在 HTTP CLI 组装中向 confirmer 与 TaskService 注入同一审批/receipt 权威实例，并验证资源生命周期。

## 4. 验证、文档与里程碑

- [ ] 4.1 增加真实 loopback verifier，覆盖审批签发、任务绑定、一次消费、receipt 确认和 unknown 显式恢复，并扫描公开面无 secret、goal、raw arguments、路径或异常泄漏。
- [ ] 4.2 更新 HTTP/threat-model 文档，完成两轮代码与契约自审，修复发现后通过聚焦/全量 pytest、Ruff、format、OpenSpec strict 和 Comet verify。
- [ ] 4.3 同步主规格、归档 change，产出 M44 里程碑记录并推送开发分支；不执行 PyPI、tag 或发布自动化。
