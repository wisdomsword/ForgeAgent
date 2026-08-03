# Brainstorm Summary

- Change: harden-client-lifecycle-and-input-contracts
- Date: 2026-08-01

## 已确认的技术事实

- 当前 provider SDK client 在 complete/stream 请求中重复创建，且没有确定性关闭。
- `Task.close()` 当前只拥有 backend 资源；外部注入的 `ModelClient` 不应由 Task 隐式关闭。
- CLI、smoke、evaluate、HTTP 和协作入口的 client 所有权需要按创建方统一收敛。
- `GenerationParams`、`ModelCapability` 和 `ModelEntry` 允许零值/负值；provider request builder 使用 truthiness 回退。
- 生命周期 verifier 的 `ast.dump()` 摘要在 Python 3.11、3.12、3.14 上不同，未改变源码也会失败。

## 已确认的技术方案

采用方案 1：provider client 懒创建并共享一个 SDK client，幂等 close；创建方负责关闭；Pydantic 边界做有限正数校验；verifier 以规范化源码片段摘要。

方案 2（每次请求创建并关闭 SDK client）不采用：无法复用连接池，也难安全覆盖流式生命周期。

方案 3（让 Task 统一关闭 client）不采用：会破坏外部注入/共享 client 的所有权边界。

## 已确认的错误处理决策

- SDK close 失败时保持主流程结果，仅输出固定类型安全日志并继续其他清理；关闭异常不得覆盖真实任务结果，也不得泄漏 raw exception。

## 测试策略

- provider client 复用、stream/complete 共用、重复 close、注入 transport 不被关闭。
- CLI/HTTP/evaluate/smoke 的成功、预检失败、取消和异常清理。
- zero/negative/NaN/infinity 参数拒绝及正值兼容。
- Python 3.11/3.12/3.14 verifier 摘要一致且源码变更仍失败。
