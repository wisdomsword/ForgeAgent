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

## Migration Plan

这是加法变更：默认不创建 checkpoint，现有 CLI/HTTP 请求无需迁移。出现实现回滚时，旧版本会忽略新 `loop` CLI 和 HTTP 可选字段；checkpoint 使用版本字段，未知版本 fail closed，不做自动降级或改写。

## Open Questions

无。token budget 必须由新 Loop 显式提供；其余默认预算为累计 rounds 50、墙钟 3600 秒、连续失败 3，并由测试和文档同步。
