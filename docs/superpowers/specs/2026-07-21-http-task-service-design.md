---
comet_change: http-task-service
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-22-http-task-service
status: final
---

# M16 HTTP Task Service 与审计日志技术设计

## 1. 设计结论

M16 使用 Python 标准库 `http.server.ThreadingHTTPServer`，不新增运行时依赖。服务只监听 loopback；非-loopback 地址直接拒绝，M16 不提供 TLS。HTTP 是本地、单用户、headless 入口，不是远程多租户 API。

服务拥有一个有界 `TaskService`：默认最多 4 个 worker、32 个排队任务、256 条保留记录；终态记录默认保留 1 小时。容量耗尽返回明确的 `429 capacity_exceeded`，不淘汰运行中的任务。所有上限都是配置项，但配置值本身由服务端持有。

HTTP 请求只允许 `goal` 以及明确列入 schema 的低风险选项。`tier`、`backend`、`allowed_root`、`container_image`、identity/trust record、confirmer、API 凭据和 MCP 连接策略不能由客户端覆盖。服务端通过 task factory 装配这些策略。

## 2. 组件和责任

### 2.1 `HttpServiceConfig`

配置对象从用户配置和专用环境变量装配：环境变量 `FORGEAGENT_HTTP_TOKEN` 优先于配置文件中的 token；两者都为空或只含空白时拒绝启动。token 只在内存中保存，不写日志，不提供进程内热轮换；修改后重启服务生效。

配置还包含 loopback bind 地址、端口、worker/queue/retention 上限、审计路径/轮转参数和 HTTP allowlist。非-loopback bind 在校验阶段拒绝，不通过“警告后继续”的降级路径。

### 2.2 `TaskService` 与 `TaskRecord`

`TaskService` 负责注册表、队列、worker executor、task id 生成、状态锁和服务关闭。`TaskRecord` 至少包含：

- task id、创建/开始/结束时间；
- `queued`、`running`、`completed`、`answered_in_prose`、`refused`、`needs_info`、`failed`、`cancelled` 等状态；
- `threading.Event` 取消信号；
- 安全结果投影和 audit degraded 标志；
- worker future 与资源关闭状态。

提交在 registry 锁内完成容量检查、记录发布和队列入列，避免“返回 task id 但没有 worker”的半状态。达到队列或保留记录上限时不创建记录。终态记录由 TTL/最大记录数清理；运行中记录不被淘汰。过期 id 返回同一安全的 not-found/expired 语义。

worker 为每个 task 创建一个 client、backend、`Task` 和 task-scoped audit context；worker 在 `finally` 中先关闭 `Task`/backend，再释放 client 资源。若服务使用共享 MCP manager，manager 由 service 持有，并在停止接收新任务、等待 worker bounded join 后统一关闭。

### 2.3 取消语义

新增 `Termination.CANCELLED`，并在 `TaskStatus.reason` 中以 `cancelled` 暴露。排队任务在 registry 锁内设置取消并直接进入终态，不调用模型或工具。运行中任务只在安全边界停止：`Step` 在开始下一轮前、工具执行后和准备发布终态前检查 event。

取消请求与其他终态发布通过同一状态锁排序：已经发布的终态不被覆盖；取消先发布则后续完成/失败结果被丢弃并记录 cancellation；模型或工具调用正在进行时不强杀线程。取消接口只等待有界的状态变更 acknowledgement，客户端通过查询获取最终终态；重复取消是幂等的。

### 2.4 HTTP handler

handler 只做请求解析、Authorization 校验、路由、大小限制和 JSON 序列化，不直接构造 gated tool 或执行模型：

| 方法 | 路径 | 成功响应 |
|---|---|---|
| `POST` | `/tasks` | `202`，返回 `task_id` 和 `queued` 状态 |
| `GET` | `/tasks/{task_id}` | `200`，返回状态或安全终态投影 |
| `POST` | `/tasks/{task_id}/cancel` | `202`/`200`，返回 cancellation acknowledgement/current state |

不存在 health、shutdown、文件上传或流式路由。shutdown 由拥有 service 的进程控制。

请求必须带 `Authorization: Bearer <token>`，scheme 和 token 解析严格、空值拒绝，比较使用常量时间函数。错误 envelope 固定为 `{error: {kind, detail}}`；detail 不包含 traceback、token、API key、原始工具参数、文件内容或绝对路径。请求 body 默认上限 64 KiB，未知 method/path、错误 Content-Type、JSON 解析失败和超限均返回确定的 4xx。

安全结果投影只包含状态、reason、掩码/截断后的 detail、round_count、可用 token usage 摘要和 audit degraded 标志；不返回完整 `RoundResult`、prompt、模型原文、工具参数、文件内容或 host path。detail 与列表元素均有字符/字节上限。

### 2.5 HTTP headless confirmer

HTTP confirmer 复用现有 `Confirmer` 接口，但只读取 HTTP allowlist。allowlist 使用规范化后的精确操作键，不支持 glob：

- MCP：`server/tool`；
- FileWrite：canonical project-relative path；
- WebFetch：`scheme/host/port/path`，查询参数不作为可写入的授权范围。

HTTP 不读取 MCP server 的 `autoApprove`；`autoApprove` 只保留 CLI/REPL 非交互兼容语义。allowlist 命中记录 `preapproved` 决策，不命中返回 headless denial 反馈并不等待输入。所有确认决定进入 audit sink。

## 3. 审计设计

### 3.1 事件模型

新增注入式 `AuditSink` 和 task-scoped context。每条记录是一个完整 JSON 对象，字段至少包含：`timestamp`（UTC RFC3339-Z）、`event_type`、`task_id`（可选）、`risk_level`、`operation_id`、`attempt`（模型 retry/stream 需要时）、`parameters`（已掩码）、`result_status`、`duration_ms` 和 `audit_degraded`。

事件范围为：

1. 每个逻辑工具操作一条 tool event；
2. 每次模型请求 attempt/outcome 一条 LLM event；
3. 每次确认门决定一条 confirmation event；
4. HTTP submit、auth failure、query、cancel、capacity rejection、headless denial 各一条 lifecycle event。

事件在进入 JSON 序列化前复用 `secret_policy`，路径/URL 使用已有安全摘要规则。完整 prompt、文件内容、token、API key、绝对 host path 永不写入。

### 3.2 写入、轮转和失败

单进程内使用锁保护 append 和 rotate；每次写入必须形成一条完整 JSONL。达到 byte limit 前先轮转，超过 retention count 的旧文件删除。启动时创建/打开 audit path 失败会阻止 HTTP service 启动；运行时写入失败不阻塞 CLI/worker（fail-open），设置 service/task 的 degraded 标志并写固定、无敏感信息的诊断，响应中不得声称该事件已持久化。

## 4. 数据流

```text
HTTP handler
  -> auth + bounded JSON parse
  -> TaskService.submit / query / cancel
  -> TaskRecord + Task factory
  -> Task -> Step -> ModelClient / ToolRegistry / Confirmer
                    \-> AuditSink(task context) -> masked JSONL
```

HTTP 与 CLI 的差异只在入口装配：CLI 使用现有交互 confirmer，HTTP 使用 headless allowlist confirmer；Task/Step 的协议解析、sandbox、工具执行和 completion 语义共用。

## 5. 错误与并发边界

- registry 锁只覆盖状态/记录发布，不覆盖模型、工具、文件或 audit I/O。
- worker unexpected exception 映射为该 task 的 safe `failed` 终态，不影响其他记录。
- cancellation、completion、failure 的终态发布必须走同一锁和一次性 CAS 语义。
- HTTP handler 线程不直接执行任务；executor worker 数量有界，request body/header 和 task queue 有界。
- service shutdown 先停止接收新任务，再设置 queued cancellation，等待 running worker 的 bounded join，最后关闭共享 MCP manager 和 HTTP server。

## 6. 测试策略

### 单元测试

- 配置优先级、空 token、loopback-only、Authorization 解析和 body/response 上限；
- TaskRecord 状态机、容量/TTL/eviction、取消竞态和一次性终态发布；
- safe result projection 的 masking、截断和不输出 prompt/path/content；
- allowlist 精确 key 规范化、HTTP 不继承 `autoApprove`；
- AuditSink 字段、attempt/operation id、掩码、非法值 fallback、轮转、并发 append 和 fail-open degraded。

### 集成和验收

- 临时 loopback `ThreadingHTTPServer` 上并发提交 N 个 mock task，断言互不串扰；
- queued/running/terminal/cancelled/expired/容量满的完整状态矩阵；
- HTTP golden 子集回放与 CLI/mock replay 的 status/reason parity；
- audit JSONL 逐行/逐字段断言，覆盖 HTTP lifecycle、tool、LLM、confirmation 三类事件及原始 secret 缺失；
- service shutdown 后无 worker、MCP manager 或 server 线程泄漏；
- Ruff、全量 pytest、golden runner、`git diff --check` 和 threat-model 文档一致性检查。

## 7. 安全与回滚

监听只允许 loopback，token 不记录、不回显；allowlist 不支持通配符；客户端不能改变 sandbox/path/identity/credential 策略。M16 不承诺远程安全部署或 TLS。回滚只需关闭 HTTP 配置或移除新模块，既有 CLI/Task API 不受影响。
