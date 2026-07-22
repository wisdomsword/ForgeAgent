## 1. 配置与核心契约

- [x] 1.1 定义 HTTP 服务配置：loopback 绑定、bearer token、worker 上限、任务保留、审计路径/轮转和 headless allowlist，并在 token 缺失时拒绝启动。
- [x] 1.2 定义严格 HTTP 请求 schema，拒绝客户端提交 tier、backend、allowed-root、container、identity 和 credential 字段；定义有界安全结果投影及响应限制。
- [x] 1.3 增加任务生命周期/取消原语，定义独立 cancelled 终态和竞态优先级，同时保持既有 CLI 调用方兼容。

## 2. 审计日志

- [x] 2.1 实现注入式 audit sink：稳定字段、UTC 时间、task correlation、风险级别、secret masking 和安全 fallback 序列化。
- [x] 2.2 实现加锁 JSONL 写入与按字节轮转/保留；按用户裁决验证审计不可用时的 fail-open 或 fail-closed 行为。
- [x] 2.3 定义 event idempotence/attempt 字段，为模型请求 attempt、逻辑工具操作和 confirmer 决策添加核心埋点。
- [x] 2.4 根据 Design 裁决决定并实现 HTTP 提交、鉴权失败、查询、取消、拒绝等生命周期事件是否进入审计流。

## 3. 任务服务

- [x] 3.1 实现有界内存任务注册表和 worker executor，支持异步提交、状态/结果保留与任务隔离。
- [x] 3.2 定义并实现 queue-full、结果 TTL/eviction、请求并发/body 上限和 unknown/expired task 语义。
- [x] 3.3 将协作式取消接入 Task/Step 的轮次和工具边界，保证幂等、有界且不强杀线程。
- [x] 3.4 定义并测试每个 task 的资源所有权/close 顺序和 service shutdown 清理；worker 失败必须只影响自身任务。

## 4. HTTP 适配与 headless 确认门

- [x] 4.1 按 Design 最终选型实现 HTTP adapter 和 `POST /tasks`、`GET /tasks/{id}`、`POST /tasks/{id}/cancel` 路由，覆盖 method/body/size 校验。
- [x] 4.2 实现常量时间 bearer 鉴权、loopback 默认绑定、结构化错误 envelope 和有界安全结果序列化。
- [x] 4.3 实现非交互 confirmer/HTTP allowlist，并接入 WebFetch、FileWrite、MCP；HTTP 明确不继承 MCP `autoApprove`。
- [x] 4.4 接入 opt-in CLI/config 启动，同时保持既有 CLI 和直接 `Task` 构造行为。
- [x] 4.5 定义并测试 Authorization 解析、token rotation/reload、非 loopback/TLS 政策和审计文件权限。

## 5. 验证与文档

- [x] 5.1 增加配置、状态迁移、取消竞态、鉴权失败、错误脱敏、结果投影和任务隔离单测。
- [x] 5.2 增加审计事件字段、attempt/idempotence、secret/path masking、异常值、并发写入、轮转、保留和不可用 sink 测试。
- [x] 5.3 增加 loopback HTTP 集成测试：并发提交、状态轮询、结果、取消、allowlist、shutdown、容量和过期 task。
- [x] 5.4 通过 HTTP 路径回放代表性离线 golden 子集，并断言与 CLI/mock replay 结果一致。
- [x] 5.5 更新 `README.md`、`docs/threat-model.md` 和服务配置文档，说明监听、token、审计、取消、结果投影及 headless 确认边界。
- [x] 5.6 运行 Ruff、专项测试、全量 pytest、golden runner 和 `git diff --check`，记录 M16 收尾证据。
