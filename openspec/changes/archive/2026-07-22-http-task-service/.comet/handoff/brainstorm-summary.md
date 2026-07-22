# Brainstorm Summary

- Change: http-task-service
- Date: 2026-07-21

## 已确认的上下文

- M16 作为一个 change，提供本机 headless HTTP 任务入口与核心层 JSONL 审计。
- HTTP 只接受严格 request schema；sandbox/path/identity/credentials/confirmer 等安全策略由服务端拥有。
- HTTP gated tool 只认显式 headless allowlist；MCP `autoApprove` 保留给 CLI/REPL，不继承到 HTTP。
- 任务注册表、结果投影、取消终态、审计失败模式、生命周期事件范围、资源关闭责任等需要在 Design 阶段细化。

## 候选方案

- stdlib `ThreadingHTTPServer`：已确认；零新增依赖，需手写解析、错误 envelope 和限制。
- FastAPI：校验与文档生态较强；新增依赖和生命周期抽象。
- `uvicorn` + 手写 ASGI：server 能力较强；仍新增依赖，当前部署需求不足。

## 已确认的技术裁决

- HTTP 仅监听 loopback；拒绝非-loopback 绑定；M16 不提供 TLS。
- token 支持用户配置字段或专用环境变量，环境变量优先；空/空白 token 拒绝启动；进程内不做热轮换，重启生效。
- HTTP 只接受严格低风险 request schema；sandbox/path/identity/credentials/confirmer 等均为服务端策略。
- 任务默认 worker=4、队列=32、终态 TTL=1h、最多保留 256 条记录；达到容量返回明确 429/容量错误，不淘汰运行中任务。
- 结果只返回安全投影（状态、原因、掩码/截断 detail、轮次计数和用量摘要），不返回 prompt、原始 tool 参数、文件内容、绝对路径或完整 rounds。
- 新增 `Termination.CANCELLED`；排队取消立即终态；运行中在轮次/工具安全边界停止；终态发布采用锁序，先发布者胜，取消不会强杀正在进行的 provider 调用。
- 审计 sink 启动初始化失败时服务启动失败；运行时写入失败采用 fail-open，但标记 degraded 并写固定诊断，不声称事件已持久化。
- 审计覆盖工具逻辑操作、模型 request attempt、确认门，以及 HTTP submit/auth/query/cancel/reject 生命周期事件；HTTP token 和原始敏感参数永不落盘。
- HTTP allowlist 使用精确规范化操作键：MCP=`server/tool`、FileWrite=canonical project-relative path、WebFetch=scheme/host/port/path；不支持 glob。
- HTTP service 拥有 worker/task registry 和 per-task Task/backend/client；共享 MCP manager 由 service 在所有 worker 停止后统一关闭。

## Spec Patch

- 已回写 OpenSpec：明确 HTTP 不继承 MCP `autoApprove`，并补充严格请求 schema、安全结果投影、取消/容量/过期边界。
