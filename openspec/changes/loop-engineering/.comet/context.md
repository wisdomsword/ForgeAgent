# Comet Design Handoff

- Change: loop-engineering
- Phase: design
- Mode: compact
- Context hash: 3c040f78e3e2372ae1e15528f886931aef2ebce23ba69bf33a37d52946ec6cdb

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/loop-engineering/proposal.md

- Source: openspec/changes/loop-engineering/proposal.md
- Lines: 1-31
- SHA256: 0869a81cb053a3914c4b7a215a6623ede23f92c037803a36b3d20fdabcd076dd

```md
## Why

ForgeAgent 目前只能把一次 `Task` 执行到终态；长任务被进程中断后无法从耐久状态续接，也没有统一的 token、墙钟和连续失败停止预算。M21 需要在不改变现有 `Step` 单任务反馈语义、也不提前引入 M22 多角色验收的前提下，增加一个可由 CLI、HTTP 和操作系统调度器触发的轻量持久化 Loop。

## What Changes

- 新增 Task 之上的 Loop 控制层：按迭代调用现有 Task，持久化进度、未解问题、交接反馈、预算消耗和终态报告。
- 新增原子 checkpoint 与显式 resume；恢复时校验版本、任务身份和配置兼容性，并保证已提交完成的迭代不重复执行。
- 新增统一停止条件：迭代/轮次上限、累计 token 预算、任务级墙钟预算、连续失败上限和协作取消；任一命中均写入可诊断终态。
- 新增失败收敛反馈：可恢复失败的有界摘要进入下一迭代，不可恢复失败或预算耗尽立即停止，禁止无限重试。
- 新增 `forgeagent loop` CLI 入口，并让现有 HTTP 任务提交接口可选地启动或恢复 Loop；普通 `run`、REPL、serve 单任务语义保持不变。
- 新增本地 cron/launchd/systemd 触发示例和一个只产出报告、不自动创建 PR 的端到端 Loop 示例；不内置 scheduler 守护进程。
- 新增 Loop 生命周期审计事件和离线确定性测试；M20 Evaluator 保持显式 opt-in，不自动接入普通 Task 或 Loop。

## Capabilities

### New Capabilities

- `loop-execution`: 定义持久化 Loop 的触发、checkpoint/resume、预算停止、失败收敛、终态报告和兼容性边界。

### Modified Capabilities

- `http-task-service`: 现有任务提交请求新增可选 Loop 启动/恢复模式，同时保持普通任务请求和响应兼容。
- `audit-logging`: 增加有界、脱敏的 Loop 生命周期与 checkpoint 审计事件，不记录 checkpoint 正文或敏感配置。

## Impact

- 主要影响 `Task` 之上的新 Loop 模块、CLI 装配、HTTP task service/server 和审计事件投影；`Step` 的轮内协议、工具执行和完成判定不改变。
- checkpoint 只写入用户指定或配置允许的项目根目录，采用版本化 JSON 和原子替换；不引入数据库、常驻服务、新依赖或自动工作树管理。
- HTTP 保持原有 endpoint，通过可选请求字段选择单任务或 Loop；现有调用方无需修改。
- 离线 CI、20 项 trusted golden core 和真实模型显式 opt-in 成本边界保持不变。

```

## openspec/changes/loop-engineering/design.md

- Source: openspec/changes/loop-engineering/design.md
- Lines: 1-87
- SHA256: 18559a456c4580669664c36a1ed71855b6eb2375b9223aed11db699ddc09f1d2

[TRUNCATED]

```md
## Context

现有 `Task.run()` 每次创建一个 `Step`，在单个对话内按 max rounds 运行并返回 `TaskOutcome`；CLI `run` 与 HTTP worker 都直接调用这一边界。M10 已提供逐轮 `TokenUsage`，M16 已提供线程池、取消、HTTP 安全投影和审计，M17–M19 提供长上下文、Memory 与 Skills，M20 的 Evaluator 则明确保持 opt-in。M21 需要组合这些能力，但不能把活跃模型会话、Python runtime 或工具内部状态当成可安全序列化的 durable state。

## Goals / Non-Goals

**Goals:**

- 在 `Task` 上方增加一个小型持久化 Loop 控制器；每次迭代仍运行现有 Task。
- 通过 Loop 专用 `Checkpoint` 工具在 Task 中途原子提交耐久进度，并在 Task 返回后自动提交累计预算与终态。
- 让 CLI、HTTP 和外部操作系统调度器使用同一 checkpoint/resume 与停止语义。
- 对累计轮次、token、墙钟、连续失败和取消实施确定、可测试的停止边界。
- 保持普通 Task、离线 CI、trusted golden core 与 M20 Evaluator 成本边界不变。

**Non-Goals:**

- 不序列化或恢复模型 conversation、`Runtime`、`CodeBlockStore`、executor 进程或未提交副作用。
- 不新增 scheduler daemon、数据库、工作流框架、worktree 自动化、新依赖或 HTTP endpoint。
- 不实现 M22 Planner/Generator/Evaluator、自动打回验收或完成标准清单。

## Decisions

### 1. 在 Task 上方编排，而不修改 Step 状态机

新增 `loop.py`，包含严格 Pydantic checkpoint/report 模型、`LoopRunner`、`CheckpointTool` 和原子 store。`LoopRunner` 接收一个按迭代构造 Task 的 callable；每次 Task 使用新 conversation/runtime/backend，Loop 只持久化跨迭代事实与累计预算。

备选 A 是扩展 `Step` 使其直接 resume；它要求序列化 conversation、blocks、runtime 和工具状态，恢复语义脆弱且扩大核心 blast radius。备选 B 是引入通用 workflow engine；M21 只有串行单 Loop，没有证据需要 DAG、队列或插件抽象。选择 Task 上层控制器是最小可用边界。

### 2. checkpoint 采用单个严格 JSON 快照与原子替换

默认路径为 `<allowed_root>/.forgeagent/loops/<loop_id>.json`；Loop ID 使用 32 位小写 hex，HTTP resume 只接收该 ID，客户端不能指定路径。读写均拒绝 symlink root/file，按 realpath/commonpath 锁定 allowed root，设置文件大小与文本/条目上限，使用 sibling `NamedTemporaryFile` + flush/fsync + `os.replace`。模型调用 `Checkpoint` 成功时，store 在工具返回前完成原子提交；Task 结束后 runner 再提交累计 counters、失败摘要和终态。

Checkpoint 只保存：schema、loop_id、goal、冻结 budgets、iteration/round/token/elapsed/failure counters、completed items、open questions、handoff、last failure、status/stop reason 和 revision。它不保存 prompt、tool arguments、代码块、完整模型输出或 secret。

### 3. Loop 专用 Checkpoint 工具通过现有 ToolRegistry 注入

为 Loop Task 创建 `default_registry(with_mcp=..., skills=...)`，再注册低风险 `CheckpointTool`。工具参数只允许 `completed_items`、`open_questions`、`handoff`，采用 replace/ordered-deduplicate 语义与固定上限。Loop system prompt 追加一段简短协议：开始时读取耐久状态，完成实质进度后调用 Checkpoint，禁止把调用当成任务完成。

Checkpoint 不加入全局默认 registry，因此普通 Task 看不到该工具。工具失败成为现有 `ToolOutcome(success=False)`，自然进入 Step 反馈环；无需修改 parser 或 dispatch。

### 4. 恢复从冻结 snapshot 继续，而不是接受覆盖参数

新 Loop 创建时冻结 goal、模型/执行相关非敏感 identity（用于兼容检查）和 budgets。CLI `--resume LOOP_ID` 与 HTTP resume 不允许同时提供 goal/budgets；恢复加载 snapshot，若终态则直接返回原报告。下一迭代 goal 由原目标、completed/open/handoff、last failure 和明确的“不要重做已完成项”组成，且所有文本经过有界渲染。

模型、tier、allowed root、identity/MCP 等安全执行策略仍由当前 CLI/server 装配决定；checkpoint 不携带可提升权限的配置。对会改变完成标准的 goal/budget 覆盖直接拒绝。

### 5. 停止预算在迭代边界累计，墙钟使用 watchdog 协作取消

- `max_rounds`：累计所有 Task 的实际 `len(outcome.rounds)`；达到上限后不再创建 Task。每个 Task 的 `max_rounds` 取“剩余 Loop rounds”和现有配置上限的较小值。
- `token_budget`：累计每轮 `input + output + cached + reasoning` 的非负值。配置预算后，若一个有成功 reply 的迭代所有 token 字段仍为 0，则以 `token_usage_unavailable` 终结，避免未知用量绕过上限。
- `wall_clock_seconds`：checkpoint 保存已消耗秒数；每个执行段用 monotonic 计时。watchdog 在剩余预算到期时设置内部 cancel event；调用中不可强杀，返回后的首个安全边界写 `wall_clock` 终态。
- `max_consecutive_failures`：严格 completed 才清零；其它 Task 终态递增。明确 auth/invalid request/checkpoint/config failure 直接不可恢复停止。
- 外部 cancel 与 watchdog 共享组合 cancel view，不修改调用方的 event。

当多个条件同时可见时，优先级固定为 cancelled、wall_clock、token_usage_unavailable、token_budget、max_rounds、consecutive_failures、unrecoverable_failure，保证报告稳定。

### 6. 失败反馈只传安全证据，不接入 Evaluator

runner 将 Task 的稳定 reason、工具成功/失败计数、parse error 计数和经过现有 secret masking/控制字符转义/长度限制的 detail 汇总为 `last_failure`。下一迭代只看到这一摘要与 checkpoint 交接，不看到完整历史。严格 `TaskStatus.completed` 立即完成 Loop；`answered_in_prose` 仍不是 Loop completed。

M20 Evaluator 不被 import 到普通 Loop 热路径；M22 的独立验收与打回次数也不在本变更中实现。

### 7. CLI 与 HTTP 复用现有装配和 worker 生命周期

CLI 新增 `loop` 子命令：新建模式需要 goal 和显式 token budget；resume 模式只需要 Loop ID；预算字段使用正整数/正有限数校验。累计 rounds 默认 50、墙钟默认 3600 秒、连续失败默认 3，token budget 无默认。`run_loop_once()` 复用现有 client、identity、memory、skills、MCP、confirmer、context 和 console 装配。

HTTP `POST /tasks` 保持 endpoint，通过严格 allowlist 接受 `mode: "loop"`、新建预算或 `resume_loop_id`。`TaskService` 的 factory 返回统一的 closeable runner；`TaskRecord` 增加私有 Loop report 与公开 `mode`/bounded counters。线程池、capacity、TTL、cancel 和 shutdown 逻辑仍只有一套。

### 8. 审计与公开报告只记录计数和稳定枚举

新增 `loop.start`、`loop.resume`、`loop.checkpoint`、`loop.iteration`、`loop.stop`。parameters 只含 schema、trigger、revision、预算/累计数字和 item counts；不含 goal、handoff、item text、checkpoint path 或 raw failure。CLI/HTTP 的公开 Loop 报告同样只暴露稳定枚举与计数。

## Risks / Trade-offs

- [Task 内尚未 checkpoint 的副作用可能在恢复后重做] → 文档明确 Checkpoint 是提交边界；示例和 prompt 要求每个可独立验证的步骤后提交；不承诺 exactly-once 外部副作用。
- [墙钟无法中断已在途 provider/tool 调用] → 沿用现有 cooperative cancellation，watchdog 只在安全边界生效；报告记录实际累计耗时而非伪造硬截止。
- [模型可能不调用 Checkpoint] → Task 返回后仍自动保存预算/终态；中途 kill 只能恢复到最近显式提交，这是明确契约。
- [checkpoint 文本可能成为持久化 prompt injection] → 内容按不可信数据标记、有界注入、严格 schema/控制字符/secret 处理，执行权限仍由当前装配控制。
- [HTTP 类型泛化可能扩大普通路径] → runner protocol 仅包含现有 `run/close` 形状，普通 Task 测试保持原样并新增兼容回归。


```

Full source: openspec/changes/loop-engineering/design.md

## openspec/changes/loop-engineering/tasks.md

- Source: openspec/changes/loop-engineering/tasks.md
- Lines: 1-24
- SHA256: cd4ed031cc319879f12e3dde1be74128b962df995e31dfbf3af64b80c2d83f81

```md
## 1. Loop 状态与持久化

- [ ] 1.1 以严格 Pydantic 模型实现版本化 Loop budgets、checkpoint、终态报告和不变量校验
- [ ] 1.2 实现 allowed-root/symlink/大小守卫与 sibling temp + fsync + replace 原子 checkpoint store
- [ ] 1.3 实现 Loop 专用 Checkpoint 工具、边界限制和最小 system prompt 增量

## 2. Loop 执行与停止条件

- [ ] 2.1 实现 Task 之上的 LoopRunner、新建/resume、冻结配置和有界 handoff 渲染
- [ ] 2.2 实现累计 rounds/token/wall-clock/consecutive-failure/cancel 停止语义与稳定优先级
- [ ] 2.3 实现有界失败摘要、不可恢复失败分类、Loop 生命周期审计和资源关闭

## 3. 运行入口

- [ ] 3.1 新增 `forgeagent loop` 新建/resume CLI、参数校验、输出与退出码，并保持 `run`/REPL 不变
- [ ] 3.2 扩展现有 HTTP submit schema、runner factory、公开投影和 cancellation 以支持 Loop 模式
- [ ] 3.3 添加 cron/launchd/systemd 调用示例和只产出报告的端到端 Loop 示例

## 4. 验证与文档

- [ ] 4.1 添加 checkpoint 中断恢复、不重做已完成条目、损坏/逃逸/原子失败的确定性测试
- [ ] 4.2 添加每种停止条件、失败收敛、usage unavailable、并发隔离和审计最小披露测试
- [ ] 4.3 更新 README、文本协议、威胁模型、ACTION_PLAN 与 golden 候选/可信核心边界说明
- [ ] 4.4 运行专项/全量/golden/Ruff/build/OpenSpec strict 验证并完成技术、代码、验收三轮评审

```

## openspec/changes/loop-engineering/specs/audit-logging/spec.md

- Source: openspec/changes/loop-engineering/specs/audit-logging/spec.md
- Lines: 1-20
- SHA256: 3ac2abcce286d54179cb159c68a46b9d5e1a4e4f0542832b5c2011d08056ea8e

```md
## ADDED Requirements

### Requirement: Loop lifecycle events are attributable and minimally disclosing
The core Loop path MUST emit audit events for Loop start/resume, successful checkpoint persistence, iteration outcome, and terminal stop. Events MUST carry the Loop/task correlation and bounded counters while omitting the goal, checkpoint body, handoff text, completed/pending item text, absolute checkpoint path, prompts, credentials, and raw failure detail.

#### Scenario: Loop starts or resumes
- **WHEN** a CLI or HTTP request starts or resumes a Loop
- **THEN** one lifecycle event records the public trigger kind, Loop identifier, safe budget presence/limits, and `started` or `resumed` result without goal or checkpoint content

#### Scenario: Checkpoint persists
- **WHEN** a model checkpoint or automatic iteration checkpoint is atomically committed
- **THEN** one event records Loop/task correlation, schema version, iteration and aggregate item counts, and success without item text or host path

#### Scenario: Loop iteration ends
- **WHEN** an underlying Task iteration completes or fails
- **THEN** one event records the stable Task reason and cumulative round/token/failure counters without raw model response or failure text

#### Scenario: Loop reaches terminal state
- **WHEN** a Loop completes, is cancelled, reaches a budget, or encounters an unrecoverable checkpoint/configuration failure
- **THEN** one event records the stable terminal and stop reason plus bounded counters, and serialization failure follows the existing audit-degraded behavior

```

## openspec/changes/loop-engineering/specs/http-task-service/spec.md

- Source: openspec/changes/loop-engineering/specs/http-task-service/spec.md
- Lines: 1-69
- SHA256: 32000be64b8de75ccdef8bba72061db104d4a2cdbe4f2af2ee937ef216b87c44

```md
## MODIFIED Requirements

### Requirement: Authenticated task submission

The service MUST expose an asynchronous task submission endpoint that accepts a strict JSON request schema containing a goal and only explicitly approved low-risk run options, and MUST require a configured static bearer token for every task-management request. The request MAY select the existing single-task mode or the M21 Loop mode and MAY request resume by a strict server-owned Loop identifier. Security-sensitive execution policy, sandbox/path authority, checkpoint paths, identity, confirmer, credentials, and frozen resume budgets MUST remain server-owned.

#### Scenario: Valid submission
- **WHEN** a client sends a valid bearer token and a JSON body containing a non-empty goal without Loop mode
- **THEN** the service creates one ordinary task, returns a unique task identifier, and does not wait for task completion

#### Scenario: Valid Loop submission
- **WHEN** a client sends a valid bearer token, a non-empty goal, Loop mode, and valid low-risk Loop budgets
- **THEN** the service creates one Loop task, assigns a server-owned Loop identifier and checkpoint location, returns a unique task identifier, and does not wait for Loop completion

#### Scenario: Valid Loop resume submission
- **WHEN** a client submits Loop resume with a syntactically valid server-owned Loop identifier and no conflicting goal or budgets
- **THEN** the service resolves only the matching checkpoint under its configured Loop directory and asynchronously resumes that Loop

#### Scenario: Missing or invalid token
- **WHEN** a client sends a task-management request without the configured token or with a different token
- **THEN** the service returns an authentication error and does not disclose task or Loop existence, configuration values, or the expected token

#### Scenario: Invalid request body
- **WHEN** an authenticated client submits a body with a missing, empty, or invalidly typed goal for a new task, or combines resume with a new goal or budgets
- **THEN** the service returns a structured client error and creates no task

#### Scenario: Security-sensitive request option is rejected
- **WHEN** an authenticated client submits `tier`, `backend`, `allowed_root`, `checkpoint_path`, `container_image`, identity/trust, confirmer, credential fields, or attempts to override frozen resume configuration
- **THEN** the service rejects the request without creating a task or changing the server-owned execution policy

#### Scenario: Service starts without a usable token or with a non-loopback bind
- **WHEN** the configured token is missing/blank or the configured bind address is not loopback
- **THEN** the HTTP service refuses to start and exposes no task-management listener

### Requirement: Task status and result retrieval

The service MUST expose authenticated queries for a task's lifecycle state and terminal result using the existing `TaskOutcome` semantics for ordinary tasks and a bounded Loop report projection for Loop tasks. It MUST NOT expose internal exceptions, secrets, full prompts, raw tool arguments, checkpoint contents, file contents, absolute host paths, or unbounded round history.

#### Scenario: Running task query
- **WHEN** an authenticated client queries an ordinary task or Loop that has been accepted but is still running
- **THEN** the response identifies it as running, identifies the public execution mode, and does not fabricate a terminal result

#### Scenario: Terminal task query
- **WHEN** an authenticated client queries a completed, stopped, failed, refused, needs-information, or cancelled task
- **THEN** the response includes the stable terminal status, reason, safe detail, mode, and available bounded result data

#### Scenario: Unknown task query
- **WHEN** an authenticated client queries an identifier that is not retained by the service
- **THEN** the service returns a not-found error without revealing other task or Loop identifiers or stored content

#### Scenario: Safe result projection
- **WHEN** an authenticated client queries a terminal task whose rounds or checkpoint contain prompts, tool arguments, file contents, absolute paths, or handoff text
- **THEN** the response returns only bounded status/reason/detail/mode/round-count/usage/Loop-counter fields with masking and truncation

### Requirement: Cancellation has bounded terminal semantics

The service MUST expose authenticated cancellation for accepted ordinary tasks and Loops; cancellation MUST prevent future task rounds or Loop iterations when possible, produce a distinct `cancelled` terminal state, persist a Loop cancellation checkpoint when applicable, and MUST NOT affect other tasks. The cancellation race with completion or failure MUST have deterministic precedence.

#### Scenario: Cancel before execution
- **WHEN** a client cancels a queued ordinary task or Loop before its worker begins execution
- **THEN** the task transitions to cancelled without invoking the model or tools and a Loop records cancellation before returning if its checkpoint was created

#### Scenario: Cancel during execution
- **WHEN** a client cancels a running ordinary task or Loop
- **THEN** the service requests cooperative stop at the next safe round, tool, or iteration boundary, returns a bounded acknowledgement, and eventually reports deterministic terminal cancellation

#### Scenario: Cancel an already terminal task
- **WHEN** a client cancels a task or Loop that is already terminal
- **THEN** the service leaves the terminal result and checkpoint unchanged and returns an idempotent acknowledgement

```

## openspec/changes/loop-engineering/specs/loop-execution/spec.md

- Source: openspec/changes/loop-engineering/specs/loop-execution/spec.md
- Lines: 1-103
- SHA256: 156a63c00f8a477e955cbbfbacb3d8718d7e921b0f8327c3d9195b4bc4bca19f

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: Loop 可由现有运行入口显式触发
ForgeAgent SHALL 提供显式 CLI Loop 入口，并 SHALL 允许既有 HTTP 任务提交入口选择单任务或 Loop 模式。普通 `run`、REPL 和未选择 Loop 的 HTTP 请求 MUST 保持现有单 Task 语义。项目 MUST 只提供 cron、launchd 或 systemd 等外部调度示例，不得内置 scheduler 守护进程。

#### Scenario: CLI 启动新 Loop
- **WHEN** 用户以非空目标和合法预算调用 `forgeagent loop`
- **THEN** 系统创建唯一 Loop、在项目允许根目录内生成 checkpoint，并异步或同步执行现有 Task 迭代直到完成或命中停止条件

#### Scenario: 普通入口兼容
- **WHEN** 用户调用既有 `forgeagent run`、REPL 或未声明 Loop 模式的 HTTP 任务提交
- **THEN** 系统不创建 Loop checkpoint，且 Task/Step 的完成、工具和输出语义与 M21 前一致

#### Scenario: 外部调度器触发
- **WHEN** 操作系统调度器按文档调用 `forgeagent loop` 或 HTTP 提交接口
- **THEN** ForgeAgent 无需常驻 scheduler 即可启动或恢复一次 Loop 执行

### Requirement: Loop checkpoint 是版本化、原子且有界的耐久状态
Loop SHALL 将 schema 版本、Loop 身份、原始目标、预算配置、累计预算、迭代计数、连续失败数、已完成条目、未解问题、下轮交接信息、最近安全失败摘要和终态写入 checkpoint。checkpoint MUST 位于允许根目录内，MUST 使用原子替换写入，MUST 拒绝符号链接逃逸、未知字段、超限内容、无效状态组合和不支持的 schema 版本。

#### Scenario: 模型提交进度 checkpoint
- **WHEN** Loop 专用 `Checkpoint` 工具收到合法的已完成条目、未解问题和交接信息
- **THEN** 系统在返回工具成功反馈前原子持久化新状态，并保留此前已提交完成条目

#### Scenario: 进程在 Task 中途终止
- **WHEN** 模型已成功调用 `Checkpoint`，随后进程在当前 Task 返回前被终止
- **THEN** checkpoint 仍包含已提交进度，恢复提示明确要求跳过这些完成条目

#### Scenario: checkpoint 写入失败
- **WHEN** checkpoint 目录不可写、目标发生路径逃逸或原子替换失败
- **THEN** `Checkpoint` 工具返回结构化失败，Loop 不声称进度已持久化，且失败可进入现有 Task 反馈环

#### Scenario: checkpoint 内容或版本无效
- **WHEN** resume 读取到未知 schema、额外字段、超限文本、无效计数或互相矛盾的终态
- **THEN** 系统在调用模型或工具前拒绝恢复，并保留原文件不变

### Requirement: Resume 只续接兼容且未终结的同一 Loop
ForgeAgent SHALL 支持从 checkpoint 显式恢复，恢复时 MUST 使用 checkpoint 中冻结的目标与预算配置，MUST 延续累计迭代、轮次、token、墙钟和连续失败计数，并 MUST 把已完成条目、未解问题和交接信息注入下一 Task。已终结 checkpoint MUST 只返回其既有报告，不得再次执行模型或工具。

#### Scenario: 从中断 checkpoint 恢复
- **WHEN** 用户恢复一个有效且未终结的 checkpoint
- **THEN** 下一 Task 收到原目标和耐久交接状态，累计预算从已记录值继续，已完成条目不被要求重做

#### Scenario: 试图覆盖冻结配置
- **WHEN** resume 请求同时提供不同目标、预算或安全执行选项
- **THEN** 系统拒绝冲突输入，而不是静默改变原 Loop 的完成标准或资源上限

#### Scenario: 恢复已终结 Loop
- **WHEN** checkpoint 已记录 completed、budget exhausted、cancelled 或不可恢复失败终态
- **THEN** 系统返回既有有界报告且不创建新 Task

### Requirement: 所有停止条件按累计 Loop 预算执行
Loop MUST 支持累计轮次上限、累计 token 上限、累计墙钟上限、连续失败上限和协作取消；任一条件达到或超过边界时 MUST 在下一次模型调用前停止，原子写入稳定停止原因和有界报告。预算 MUST 使用实际已完成调用的 normalized `TokenUsage`，不得把缺失 usage 猜测为零以绕过已配置 token 上限。

#### Scenario: 累计轮次预算命中
- **WHEN** 已执行轮次达到配置上限
- **THEN** Loop 以 `max_rounds` 停止，恢复不会重置轮次计数

#### Scenario: token 预算命中
- **WHEN** 已记录输入、输出、缓存和 reasoning token 的规范化累计值达到配置上限，或 provider 未提供足够 usage 证明仍在预算内
- **THEN** Loop 在下一次模型调用前以 `token_budget` 停止并报告已知累计值与 usage 缺失状态

#### Scenario: 墙钟预算命中
- **WHEN** 当前执行段耗时加历史累计耗时达到配置上限
- **THEN** Loop 请求协作取消，并在当前不可中断调用返回后的首个安全边界以 `wall_clock` 停止；恢复不会重置已消耗墙钟

#### Scenario: 连续失败预算命中
- **WHEN** 连续未完成 Task 迭代达到配置上限
- **THEN** Loop 以 `consecutive_failures` 停止，成功完成才清零连续失败计数

#### Scenario: 外部取消
- **WHEN** CLI 中断或 HTTP cancellation 设置协作取消信号
- **THEN** Loop 不再启动新 Task，并以 `cancelled` 终结且不影响其他 Loop 或普通任务

### Requirement: 失败反馈环有界收敛且不引入独立 Evaluator
每个 Loop 迭代 SHALL 运行一个现有 Task；非完成结果 SHALL 生成脱敏、有界的失败摘要并与最近 checkpoint 交接信息一起进入下一迭代。Loop MUST 在停止预算内尝试修正，MUST 对明确不可恢复的配置、鉴权、checkpoint 或策略错误立即停止，并 MUST NOT 自动调用 M20 Evaluator 或实现 M22 Generator/Evaluator 打回语义。

#### Scenario: 可恢复失败后修正成功
- **WHEN** 一个 Task 因工具失败、上下文限制或轮次耗尽而未完成，但尚未命中 Loop 停止条件
- **THEN** 下一 Task 收到有界失败证据和继续要求，最终完成时 Loop 写入 completed 终态

```

Full source: openspec/changes/loop-engineering/specs/loop-execution/spec.md
