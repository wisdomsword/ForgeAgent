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

- **[风险]** 进程重启会丢失内存记录。→ 明确这是进程级保留语义，持久 artifact 仍由既有 workdir 承担。
- **[风险]** 协作式取消不能立即停止阻塞的外部调用。→ 每个安全边界检查，限制 acknowledgement 等待，并诚实报告最终状态。
- **[风险]** stdlib handler 的护栏少于框架。→ 限制路由面，集中解析/鉴权/error envelope，并覆盖 malformed request 和并发。
- **[风险]** 审计可能泄露敏感数据或无限增长。→ 复用 masking，清理路径/URL，加锁写入，按大小轮转，并断言原始 secret 不落盘。
- **[风险]** 客户端运行选项可能提升 sandbox/path 权限。→ 严格 request schema，安全策略全部服务端拥有，并测试拒绝相关字段。
- **[风险]** 结果查询可能泄露模型/工具数据。→ 有界安全投影、掩码和字段/字节上限。
- **[风险]** 非 loopback 监听扩大攻击面。→ 默认 loopback，显式配置、token/TLS 边界和 threat model 更新。

## 迁移计划

无需数据迁移。HTTP 服务和审计模块通过 opt-in 配置接入；既有 CLI 和直接构造 `Task` 的路径不启动 HTTP listener。回滚方式是关闭服务配置或回退新增模块，既有任务和工具 API 保持可用。

## 设计裁决

以上细节已在 `docs/superpowers/specs/2026-07-21-http-task-service-design.md` 中完成技术裁决：stdlib server、本机-only、严格请求 schema、安全结果投影、`CANCELLED` 状态、容量/TTL 上限、审计启动 fail-closed + 运行时 fail-open degraded、HTTP 生命周期审计、精确 allowlist 和资源 close 顺序。
