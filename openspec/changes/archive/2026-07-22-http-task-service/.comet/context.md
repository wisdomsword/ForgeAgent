# Comet Design Handoff

- Change: http-task-service
- Phase: design
- Mode: compact
- Context hash: 228f200e58895ec12f9bb5cfe335209c94c68c0c0767afc8c236cf088140bc04

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/http-task-service/proposal.md

- Source: openspec/changes/http-task-service/proposal.md
- Lines: 1-31
- SHA256: e9a1d9306f1b7ca62069e5255b9afd830cfa25480d49833e4a01b418ba81f306

```md
## Why

ForgeAgent 当前只有 CLI 入口，无法被 cron、CI 或其他本地程序可靠触发；同时工具执行、模型调用和确认门缺少统一的可追溯记录。M16 在 M15 身份层之后补齐一个轻量的 headless HTTP 入口，并把审计留痕放在核心执行层，使 CLI 与 HTTP 共享同一安全和诊断语义。

## What Changes

- 新增异步任务 HTTP API：提交任务、查询状态与结果、取消任务。
- 新增静态 bearer token 鉴权、结构化错误响应和并发任务隔离。
- 新增核心层 JSONL 审计事件，覆盖工具执行、LLM 调用和确认门决策。
- 审计参数摘要复用现有 secret masking，并提供有界的按大小轮转配置。
- 将 HTTP headless 请求接入现有 non-TTY 确认门语义：gated tool 默认拒绝，可由显式 allowlist 预授权。
- 更新威胁模型、服务配置/运行文档和 M16 专项测试；保持既有 CLI 任务语义兼容。

## Capabilities

### New Capabilities

- `http-task-service`: 本地 headless HTTP 服务、任务生命周期 API、鉴权、并发和取消语义。
- `audit-logging`: 核心层 JSONL 审计事件模型、掩码、轮转和共享埋点语义。

### Modified Capabilities

- `tool-approval`: 明确 HTTP/non-TTY 路径的 gated tool 拒绝与显式预授权 allowlist 语义。

## Impact

- 代码：新增 HTTP 服务/任务仓库与审计模块；修改 `Task`/`Step`、工具注册表、LLM client、确认器和 CLI 装配。
- API：新增本地 HTTP 端点与 JSON 响应契约；既有 Python/CLI API 保持兼容。
- 配置：增加监听地址/端口、静态 bearer token、审计路径/轮转和 headless allowlist 配置。
- 测试：并发任务集成测试、HTTP golden 子集回放、逐字段审计断言、鉴权/取消/确认门边界测试。
- 文档与安全：更新 `README.md`、`docs/threat-model.md`，记录监听面、token 泄露、日志残留和本地绑定边界。

```

## openspec/changes/http-task-service/design.md

- Source: openspec/changes/http-task-service/design.md
- Lines: 1-95
- SHA256: 6c26368793be5865cdca8b7ac016e5280e22aeb16357988d691dc9579dde92e6

[TRUNCATED]

```md
## 背景

M15 完成后，ForgeAgent 仍只有同步的 `Task.run()` 和 CLI 装配。`Step`、工具注册表、模型客户端及现有通用 confirmer 已包含权威的执行和安全语义，但没有共享任务注册表、取消信号、HTTP 适配器或持久化操作日志。M16 必须新增程序化入口，同时避免在 HTTP 层复制一套安全决策。

仓库使用 Python 3.11+，运行时依赖刻意保持轻量，目前没有 Web 框架依赖。服务定位是本机、单用户、headless 和有界的任务服务，不是多租户守护进程。

## 目标 / 非目标

**目标：**

- 提供鉴权的异步任务提交、状态/结果查询和取消接口。
- 继续复用现有 `Task`/`Step` 路径，使 CLI 与 HTTP 共享协议、sandbox、模型和确认门语义。
- 将任务关联信息传递到工具、LLM 和确认门审计事件。
- 非交互 gated tool 默认拒绝，只有显式 HTTP headless allowlist 才能预授权。
- 对任务记录、worker 并发、取消等待、结果返回和审计文件增长设置边界。

**非目标：**

- 不做 WebSocket/HTTP 流式协议、远程多用户部署、数据库、scheduler 或外部身份提供商。
- 不替换既有 CLI API 或 `TaskOutcome`；新增字段必须向后兼容。
- 不把 FileWrite confirmation 包装成高于现有 executor/project-root 控制的安全边界。

## 决策方向

### 1. 基于内存任务注册表的薄 HTTP 适配层

服务维护有界的任务记录（`queued`、`running`、终态）和配置上限的 `ThreadPoolExecutor`。每条记录包含 task id、提交元数据、取消事件、安全结果和时间戳。worker 复用正常 `Task` 路径，并在 `finally` 中释放 backend、client、MCP manager、audit context 等由它创建的资源。注册表只在进程内存在，不承诺重启后恢复。

初始路由形状为：

- `POST /tasks`：提交严格 JSON schema，必须含 `goal`，只能带明确批准的低风险运行选项，返回 `202` 和 `task_id`。
- `GET /tasks/{task_id}`：返回生命周期状态和安全终态数据。
- `POST /tasks/{task_id}/cancel`：请求协作式取消，返回当前状态。

`backend`、`tier`、`allowed_root`、`container_image`、identity/trust record、confirmer 和模型凭据等安全敏感项只能由服务端配置，HTTP 客户端不可提交。结果是 `TaskOutcome` 的有界安全投影：不返回完整 prompt、原始工具参数、文件内容、宿主绝对路径或无限历史，并设置字节/条目上限。

所有路由共用 JSON 错误 envelope 和 bearer token。队列满、记录过期、未知 task id、请求体过大等边界必须有确定的错误语义。

### 2. HTTP 实现选型（已裁决）

已确认使用 `http.server.ThreadingHTTPServer`，配合小型 handler 和显式 JSON 序列化：零新增运行时依赖，适合本机三条路由，鉴权、绑定和错误行为容易审查。HTTP server 应隔离在 service 类之后，使未来切换 ASGI 不改变注册表和路由契约。

备选方案：

| 方案 | 优点 | 成本 / 当前判断 |
|---|---|---|
| FastAPI | 校验、OpenAPI、生态成熟 | 新依赖和另一套生命周期/并发抽象；当前范围暂不需要 |
| `uvicorn` + 手写 ASGI | server 能力较成熟 | 仍需新增依赖，当前没有部署需求 |
| stdlib `ThreadingHTTPServer` | 零依赖、语义显式 | 需手写解析和契约；当前推荐 |

详细实现契约见 `docs/superpowers/specs/2026-07-21-http-task-service-design.md`，不能把 HTTP 框架选型重新带入 Build。

### 3. 静态 bearer token 与监听边界

token 通过现有配置装配提供，环境变量只作为密钥注入手段，不绑定任何厂商端点。缺少 token 时 HTTP 服务拒绝启动；请求使用常量时间比较，绝不回显 token。默认绑定 loopback；非 loopback 必须显式配置并在文档中声明明文 HTTP/TLS、远程暴露和信任边界。

配置键、`Authorization` 解析规则、空值/长度限制、token reload/rotation，以及审计文件权限已在技术 Design Doc 中固定。

### 4. 轮次/工具边界的协作式取消

任务记录拥有 `threading.Event`。`Step` 在新轮次开始前和工具执行后检查它；不强杀线程，也不承诺打断正在进行的模型/网络调用。必须增加独立的 `Termination.CANCELLED`/状态映射，并定义它与 completed、failed、queued-start 的竞态优先级。取消接口先返回有界 acknowledgement，worker 在安全边界收敛为唯一取消终态；重复取消幂等。

取消等待期限、队列满行为、终态结果 TTL/淘汰规则和过期查询返回值必须在 Design 阶段裁决。

### 5. 核心层 JSONL 审计 sink

新增注入式 audit sink/context，而不是只在 HTTP 层记录。`Task` 提供 task correlation；`Step`、工具执行、confirmer 和模型客户端写入结构化事件。写入前复用 `secret_policy` 掩码，在锁内写入一条 JSON 对象，按字节大小轮转并限制保留份数。

审计 sink 启动初始化失败时阻止 HTTP 服务启动；运行时写入失败采用 fail-open，但标记 degraded 并写固定诊断。事件粒度定义为：每个逻辑工具操作一条事件；每次模型请求 attempt 一条事件，retry/stream attempt 必须可区分；HTTP 提交、鉴权失败、查询、取消、容量拒绝和 headless 拒绝均记录生命周期事件。原始异常文本不得进入模型反馈。

### 6. headless confirmer 与既有 `autoApprove` 的边界

HTTP 复用现有 `Confirmer` 接口，由非交互 confirmer 判断显式 HTTP allowlist。HTTP 路径**不读取 MCP `autoApprove`**；后者继续只服务 CLI/REPL 的既有兼容语义。HTTP allowlist 的匹配对象、规范化规则、MCP server/tool、WebFetch URL 和 FileWrite 路径的精确匹配方式必须在 Design 阶段定义。每次决定都进入核心审计 sink。

### 7. 测试与生命周期

测试使用临时 loopback server、fake client/replay task 和隔离的审计路径，覆盖并发提交、取消竞态、鉴权、任务隔离、allowlist、结果投影、队列/保留上限、轮转/掩码和 HTTP golden 回放。v1 没有 shutdown HTTP 路由；owner 控制进程 shutdown，并测试有界 close 顺序。服务不得暴露未鉴权 health endpoint。

## 风险 / 取舍


```

Full source: openspec/changes/http-task-service/design.md

## openspec/changes/http-task-service/tasks.md

- Source: openspec/changes/http-task-service/tasks.md
- Lines: 1-36
- SHA256: f6f32c0b56aaf04495f889de9273f6740aadbff01500aac4937399d425670004

```md
## 1. 配置与核心契约

- [ ] 1.1 定义 HTTP 服务配置：loopback 绑定、bearer token、worker 上限、任务保留、审计路径/轮转和 headless allowlist，并在 token 缺失时拒绝启动。
- [ ] 1.2 定义严格 HTTP 请求 schema，拒绝客户端提交 tier、backend、allowed-root、container、identity 和 credential 字段；定义有界安全结果投影及响应限制。
- [ ] 1.3 增加任务生命周期/取消原语，定义独立 cancelled 终态和竞态优先级，同时保持既有 CLI 调用方兼容。

## 2. 审计日志

- [ ] 2.1 实现注入式 audit sink：稳定字段、UTC 时间、task correlation、风险级别、secret masking 和安全 fallback 序列化。
- [ ] 2.2 实现加锁 JSONL 写入与按字节轮转/保留；按用户裁决验证审计不可用时的 fail-open 或 fail-closed 行为。
- [ ] 2.3 定义 event idempotence/attempt 字段，为模型请求 attempt、逻辑工具操作和 confirmer 决策添加核心埋点。
- [ ] 2.4 根据 Design 裁决决定并实现 HTTP 提交、鉴权失败、查询、取消、拒绝等生命周期事件是否进入审计流。

## 3. 任务服务

- [ ] 3.1 实现有界内存任务注册表和 worker executor，支持异步提交、状态/结果保留与任务隔离。
- [ ] 3.2 定义并实现 queue-full、结果 TTL/eviction、请求并发/body 上限和 unknown/expired task 语义。
- [ ] 3.3 将协作式取消接入 Task/Step 的轮次和工具边界，保证幂等、有界且不强杀线程。
- [ ] 3.4 定义并测试每个 task 的资源所有权/close 顺序和 service shutdown 清理；worker 失败必须只影响自身任务。

## 4. HTTP 适配与 headless 确认门

- [ ] 4.1 按 Design 最终选型实现 HTTP adapter 和 `POST /tasks`、`GET /tasks/{id}`、`POST /tasks/{id}/cancel` 路由，覆盖 method/body/size 校验。
- [ ] 4.2 实现常量时间 bearer 鉴权、loopback 默认绑定、结构化错误 envelope 和有界安全结果序列化。
- [ ] 4.3 实现非交互 confirmer/HTTP allowlist，并接入 WebFetch、FileWrite、MCP；HTTP 明确不继承 MCP `autoApprove`。
- [ ] 4.4 接入 opt-in CLI/config 启动，同时保持既有 CLI 和直接 `Task` 构造行为。
- [ ] 4.5 定义并测试 Authorization 解析、token rotation/reload、非 loopback/TLS 政策和审计文件权限。

## 5. 验证与文档

- [ ] 5.1 增加配置、状态迁移、取消竞态、鉴权失败、错误脱敏、结果投影和任务隔离单测。
- [ ] 5.2 增加审计事件字段、attempt/idempotence、secret/path masking、异常值、并发写入、轮转、保留和不可用 sink 测试。
- [ ] 5.3 增加 loopback HTTP 集成测试：并发提交、状态轮询、结果、取消、allowlist、shutdown、容量和过期 task。
- [ ] 5.4 通过 HTTP 路径回放代表性离线 golden 子集，并断言与 CLI/mock replay 结果一致。
- [ ] 5.5 更新 `README.md`、`docs/threat-model.md` 和服务配置文档，说明监听、token、审计、取消、结果投影及 headless 确认边界。
- [ ] 5.6 运行 Ruff、专项测试、全量 pytest、golden runner 和 `git diff --check`，记录 M16 收尾证据。

```

## openspec/changes/http-task-service/specs/audit-logging/spec.md

- Source: openspec/changes/http-task-service/specs/audit-logging/spec.md
- Lines: 1-75
- SHA256: e0c823c80dd5b8bdc14ed80798fb3c417d82cb8028b47bcd866e2129b50ad067

```md
# audit-logging Specification

## Purpose

Record security-relevant ForgeAgent activity in a machine-readable, bounded JSONL audit stream shared by CLI and HTTP execution paths.

## ADDED Requirements

### Requirement: Core-layer audit events cover the execution boundary

The core execution path MUST emit audit events for every logical tool operation, every model request attempt/outcome, and every confirmation-gate decision, regardless of whether the task was started by CLI or HTTP. Retries and streaming attempts MUST be distinguishable without producing ambiguous duplicate logical-operation records.

#### Scenario: Tool execution event
- **WHEN** a tool is allowed, denied, or fails during a task
- **THEN** exactly one tool audit event records the operation type, task correlation, risk level, outcome, and duration

#### Scenario: LLM call event
- **WHEN** a model request succeeds, returns a structured client error, or is interrupted
- **THEN** one LLM audit event records the model group/identifier, safe outcome, token metadata available from the client, and duration without prompt secrets

#### Scenario: Confirmation decision event
- **WHEN** a gated tool is pre-authorized, interactively approved, or denied by the headless confirmer
- **THEN** one confirmation event records the decision, risk level, tool kind, task correlation, and safe parameter summary

### Requirement: Audit records have a stable, masked JSONL schema

Each audit line MUST be one valid JSON object containing an event timestamp, event type, task identifier when available, risk level, masked parameter summary, result status, elapsed duration, and an operation/attempt correlation when applicable; serialization MUST be append-only and parseable line by line.

#### Scenario: Complete event fields
- **WHEN** a core event is written
- **THEN** its JSON object contains the required fields with stable scalar/object types and an UTC timestamp

#### Scenario: Secret masking before persistence
- **WHEN** event parameters, model metadata, tool arguments, or errors contain known secret names or values
- **THEN** masking occurs before JSON serialization and the raw secret is absent from the resulting line

#### Scenario: Malformed event data
- **WHEN** an event field contains an unserializable value or unsafe control characters
- **THEN** the logger writes a safe fallback representation or a bounded logging error without crashing the task worker or exposing raw data

### Requirement: Audit retention is bounded and concurrent writes are safe

The audit logger MUST support configurable size-based rotation with a finite retention count, serialize concurrent writers so lines are not interleaved, and preserve valid JSONL across rotations.

#### Scenario: Rotation at size limit
- **WHEN** appending an event would exceed the configured byte limit
- **THEN** the current file is rotated before the append, old files beyond the retention count are removed, and the new event is written as a complete JSON line

#### Scenario: Concurrent event writes
- **WHEN** multiple task workers emit events concurrently
- **THEN** every accepted event is either present once in a valid JSONL file or reported through a bounded logger error, with no partial/interleaved JSON records

#### Scenario: Disabled or unavailable audit path
- **WHEN** audit logging is explicitly disabled or its path cannot be opened
- **THEN** task execution follows the documented fail-open/fail-closed configuration, and the service reports the condition without silently claiming that events were persisted

### Requirement: Audit output is minimally disclosing and operationally attributable

Audit records MUST identify the risk level and operation outcome needed for replay/diagnosis while omitting bearer tokens, API keys, full prompts, file contents, and host-absolute paths.

#### Scenario: HTTP request correlation
- **WHEN** a task is submitted, queried, or cancelled through HTTP
- **THEN** core audit events for that task carry the same task identifier and do not log the bearer token

#### Scenario: HTTP lifecycle rejection is audited
- **WHEN** HTTP authentication fails, a task is rejected for capacity, or a headless confirmation denies an operation
- **THEN** one masked lifecycle or confirmation event records the route/operation and safe result status without the token, raw request body, or sensitive arguments

#### Scenario: Audit write failure is visible but non-disclosing
- **WHEN** a runtime audit append fails after service startup
- **THEN** the task/service is marked audit-degraded, a fixed diagnostic is emitted, and no response or event claims that the failed record was persisted

#### Scenario: Restricted file or web operation
- **WHEN** a FileRead, FileWrite, or WebFetch operation is audited
- **THEN** the record contains only the existing sanitized project-relative/path or artifact summary and never raw content or an unmasked URL/host path

```

## openspec/changes/http-task-service/specs/http-task-service/spec.md

- Source: openspec/changes/http-task-service/specs/http-task-service/spec.md
- Lines: 1-99
- SHA256: b6ee8e808da6f616168bdfafd46f462063a8b83d1b30de05dd0d34640acc3086

[TRUNCATED]

```md
# http-task-service Specification

## Purpose

Provide a small, local, headless HTTP entry point for running ForgeAgent tasks without changing the existing CLI task semantics.

## ADDED Requirements

### Requirement: Authenticated task submission

The service MUST expose an asynchronous task submission endpoint that accepts a strict JSON request schema containing a goal and only explicitly approved low-risk run options, and MUST require a configured static bearer token for every task-management request. Security-sensitive execution policy, sandbox/path authority, identity, confirmer, and credentials MUST remain server-owned.

#### Scenario: Valid submission
- **WHEN** a client sends a valid bearer token and a JSON body containing a non-empty goal
- **THEN** the service creates one task, returns a unique task identifier, and does not wait for task completion

#### Scenario: Missing or invalid token
- **WHEN** a client sends a task-management request without the configured token or with a different token
- **THEN** the service returns an authentication error and does not disclose task existence, configuration values, or the expected token

#### Scenario: Invalid request body
- **WHEN** an authenticated client submits a body with a missing, empty, or invalidly typed goal
- **THEN** the service returns a structured client error and creates no task

#### Scenario: Security-sensitive request option is rejected
- **WHEN** an authenticated client submits `tier`, `backend`, `allowed_root`, `container_image`, identity/trust, confirmer, or credential fields
- **THEN** the service rejects the request without creating a task or changing the server-owned execution policy

#### Scenario: Service starts without a usable token or with a non-loopback bind
- **WHEN** the configured token is missing/blank or the configured bind address is not loopback
- **THEN** the HTTP service refuses to start and exposes no task-management listener

### Requirement: Task status and result retrieval

The service MUST expose authenticated queries for a task's lifecycle state and terminal result using the existing `TaskOutcome` semantics without exposing internal exceptions, secrets, full prompts, raw tool arguments, file contents, absolute host paths, or unbounded round history. Responses MUST use a bounded safe projection.

#### Scenario: Running task query
- **WHEN** an authenticated client queries a task that has been accepted but is still running
- **THEN** the response identifies the task as running and does not fabricate a terminal result

#### Scenario: Terminal task query
- **WHEN** an authenticated client queries a completed, failed, refused, or needs-information task
- **THEN** the response includes the stable terminal status, reason, safe detail, and available result data

#### Scenario: Unknown task query
- **WHEN** an authenticated client queries an identifier that is not retained by the service
- **THEN** the service returns a not-found error without revealing other task identifiers or stored task content

#### Scenario: Safe result projection
- **WHEN** an authenticated client queries a terminal task whose rounds contain prompts, tool arguments, file contents, or absolute paths
- **THEN** the response returns only the bounded status/reason/detail/round-count/usage projection with masking and truncation

### Requirement: Cancellation has bounded terminal semantics

The service MUST expose authenticated cancellation for accepted tasks; cancellation MUST prevent future task rounds when possible, produce a distinct `cancelled` terminal state, and MUST NOT affect other tasks. The cancellation race with completion or failure MUST have deterministic precedence.

#### Scenario: Cancel before execution
- **WHEN** a client cancels a queued task before its worker begins execution
- **THEN** the task transitions to cancelled without invoking the model or tools

#### Scenario: Cancel during execution
- **WHEN** a client cancels a running task
- **THEN** the service requests cooperative stop at the next safe round or tool boundary, returns a bounded acknowledgement, and eventually reports the deterministic terminal cancellation state

#### Scenario: Cancel an already terminal task
- **WHEN** a client cancels a task that is already terminal
- **THEN** the service leaves the terminal result unchanged and returns an idempotent acknowledgement

### Requirement: Concurrent task isolation

The service MUST execute multiple submitted tasks concurrently within configured limits while isolating task state, results, cancellation, runtime state, and audit correlation.

#### Scenario: Independent concurrent submissions
- **WHEN** multiple authenticated clients submit tasks at the same time
- **THEN** each task receives a distinct identifier and its status, result, cancellation, and audit records remain associated only with that task

#### Scenario: Worker failure isolation
- **WHEN** one task worker raises an unexpected internal error
- **THEN** that task reaches a safe failed state while other accepted tasks continue according to their own lifecycle


```

Full source: openspec/changes/http-task-service/specs/http-task-service/spec.md

## openspec/changes/http-task-service/specs/tool-approval/spec.md

- Source: openspec/changes/http-task-service/specs/tool-approval/spec.md
- Lines: 1-39
- SHA256: ec2d27d102e9851db430983814781dac508babdae6cb77a9577aa2716a0447a1

```md
# tool-approval Specification Delta

## MODIFIED Requirements

### Requirement: Terminal capability controls automatic confirmation

ForgeAgent SHALL attach the generic confirmer to restricted WebFetch, FileWrite and MCP operations independently of whether MCP servers are configured. It SHALL apply the same confirmation decision semantics to CLI, REPL, and HTTP headless execution. For HTTP tasks, the configured HTTP headless allowlist is the only non-interactive pre-approval path; the existing MCP `autoApprove` configuration remains a CLI/REPL compatibility mechanism and is not inherited by HTTP tasks.

#### Scenario: Interactive terminal run
- **WHEN** a restricted tool is requested and the command has interactive TTY input and output
- **THEN** ForgeAgent asks the user to approve or reject the operation before execution

#### Scenario: REPL operation
- **WHEN** a restricted tool is requested from a REPL whose stdin and stdout are both TTYs
- **THEN** ForgeAgent asks for confirmation before execution

#### Scenario: Non-interactive REPL operation
- **WHEN** a restricted tool is requested from a REPL whose stdin or stdout is not a TTY
- **THEN** ForgeAgent rejects the operation without invoking the confirmation input reader

#### Scenario: Non-interactive input
- **WHEN** WebFetch, FileWrite or an MCP call that still requires human confirmation is requested while stdin or stdout is not a TTY
- **THEN** ForgeAgent rejects the operation deterministically without waiting for input and identifies that no interactive confirmation channel is available

#### Scenario: Non-interactive CLI or REPL auto-approved MCP call
- **WHEN** an MCP tool is listed in that server's `autoApprove` configuration, the request originates from CLI or REPL execution, and stdin or stdout is not a TTY
- **THEN** ForgeAgent treats the explicit configuration as pre-approval and executes without an interactive prompt

#### Scenario: HTTP headless operation without allowlist entry
- **WHEN** an HTTP task requests a gated WebFetch, FileWrite, or MCP operation and the operation is not in the configured headless allowlist
- **THEN** ForgeAgent rejects it deterministically with structured feedback and does not wait for input

#### Scenario: HTTP headless operation with explicit allowlist entry
- **WHEN** an HTTP task requests a gated operation that exactly matches the configured headless allowlist
- **THEN** ForgeAgent records the pre-approval decision and executes without an interactive prompt

#### Scenario: HTTP does not inherit MCP auto-approval
- **WHEN** an HTTP task requests an MCP operation that matches the server's `autoApprove` configuration but does not match the HTTP headless allowlist
- **THEN** ForgeAgent rejects the operation as headless and does not execute it

```
