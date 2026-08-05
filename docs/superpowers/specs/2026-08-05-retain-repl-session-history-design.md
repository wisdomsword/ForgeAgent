---
comet_change: retain-repl-session-history
role: technical-design
canonical_spec: openspec
archived-with: 2026-08-05-retain-repl-session-history
status: final
---

# REPL 会话历史技术设计

## 1. 问题与不变量

REPL 当前只保留进程级服务，每次输入都只使用新的 system message 和最新 goal。修复必须恢复对话语义，同时不能延长 Task 权限生命周期。

核心不变量是：

```text
全新的 Task 状态 + 本轮 system prompt + 既有安全会话记录 + 当前用户输入
```

会话记录只是上下文，绝不初始化 backend、Runtime、task ID、文件系统授权、确认结果、receipt 或工具注册表。

## 2. 消息所有权

### 2.1 Task 输入

`Task.run()` 增加可选的既有会话消息序列。调用方省略时保持当前单次任务行为。该方法复制调用方消息，并组装：

```text
[current SYSTEM, *prior session messages, current USER]
```

既有消息不得包含 system role。现有 context policy 继续承担最终结构校验，因此非法顺序会以有界 `ContextBudgetExceeded` 在本地失败，不会到达 provider。

当前 user message 中的图片继续使用结构化 `ImageItem`。历史图片保留到重置，以便后续输入引用。若用户随后切到不支持图片的模型，沿用现有能力错误；ForgeAgent 不静默删除图片。

### 2.2 Step 输出

`Step` 把当前局部变量 `convo` 提升为本次执行可读取的状态，并在 `run()` 后提供复制快照。现有追加位置继续作为唯一事实源：

- 每次成功模型调用后的 assistant 响应；
- 工具或解析活动后的有界 user feedback；
- 不创建虚假的工具输出。

取消、context budget 失败、client error、prose 完成和轮数耗尽等正常终态都必须能读取快照。

### 2.3 TaskOutcome 传递

`TaskOutcome` 增加内部会话消息字段，设置 `exclude=True` 与 `repr=False`。`model_dump()` 和 HTTP 投影因此保持不变；该字段不包含本轮 system message。

如果执行结束时 conversation 仍以 user role 结尾，说明没有 assistant 响应被追加。Task 此时增加一条有界、宿主生成的 assistant 终态投影，使下一条顶层 user 输入仍满足合法交替；该投影不得伪造执行成功。

身份回答修复必须同时修改展示用 `RoundResult` 和会话里的末条 assistant 文本，避免用户看到的内容与下一轮上下文不一致。

## 3. Context policy

不增加第二个会话压缩器。`SlidingWindowContextPolicy` 仍接收：

```text
SYSTEM, first USER, (ASSISTANT, USER)*
```

在 provider 调用边界，当前顶层输入就是最后一组中的 USER。现有交替配对算法在消息正确组装后已经能支持多个顶层输入；实现只需把术语和测试从“初始 goal 加 Task feedback”调整为“会话锚点加 assistant/user 单元”。

策略保留当前 system prompt 和首个 user 锚点，再保留预算内最新的完整单元。它不修改 TaskOutcome 会话记录，也不改写单条消息。

## 4. REPL 接入

### 4.1 本地状态

`_cli_repl.repl()` 在 `usage_total` 与 `staged_images` 旁持有 `session_messages: list[Message]`。一个小型嵌套 Single helper 收敛当前重复的 `run_once()` 参数，并额外完成：

1. 传入 `session_messages` 快照；
2. Task 返回后，用内部 transcript 替换本地列表。

管理命令不调用这个 helper，因此不能进入模型会话。

### 4.2 普通输入与显式 Single

普通 single 路由、`/single` 和带 inline goal 的 `/image` 使用相同 helper。只要返回了 TaskOutcome，completed、failed、cancelled、refused 或 needs-information 都写入其安全 transcript。抛出异常时保留上一个已完成 transcript，并沿用现有异常行为。

### 4.3 Duo 与 Triad

`run_collaboration_once()` 接收可选的外层会话记录。每个协作角色 Task 都把该记录的副本作为 prior context，再追加该角色当前 goal。角色仍分别使用新 Task、角色专用 system prompt 和工具注册表。

协作结束后，外层 REPL 不导入 planner、generator 或 evaluator 的内部 conversation，只追加：

- 一条包含本次协作 goal 的 USER message；
- 一条包含公开报告字段的 ASSISTANT message：mode、status、stop reason、phase、counters、有界 evidence 和 execution evidence 摘要。

投影必须是确定性的，不得包含候选文件正文、evaluator 评语、内部 plan、receipt 或审计事件。

## 5. 重置命令

`/new` 与 `/reset` 是共享命令表中的同义命令。两者都：

- 清空 `session_messages`；
- 清空 `staged_images`；
- 输出一条有界确认；
- 不创建 Task 或 client。

两者保留当前 model、tier、identity/Memory/MCP 对象、skill registry、终端输入回放和 `usage_total`。它们不重载配置，配置重载仍由 `/reload` 负责。

## 6. 错误与安全语义

- 非法 transcript 在调用 provider 前本地失败。
- 无法放入预算的 transcript 沿用现有结构化 context-budget 失败。
- 描述旧批准的历史文本没有进入 `RequestFilesystemAccess` 状态的代码路径。
- 当前 system prompt 总是重新生成 Runtime Authority，宿主事实不会从历史恢复。
- 会话消息仅存在于进程内，退出即消失。
- 工具反馈在存入 transcript 前已经过 secret masking 和限额处理；原始 ToolOutcome 留在 TaskOutcome rounds，不复制到会话消息。

## 7. 测试设计

### 7.1 单元测试

- `Task.run(history=...)` 发送新 system prompt、精确复制的历史和当前 user 输入。
- TaskOutcome 会话消息不出现在 `model_dump()` 或 HTTP 结果中。
- 身份修复同步修改末条会话 assistant message。
- 无 assistant 的失败获得有界 assistant 失败投影。
- context policy 接受多输入交替，拒绝非法 role，按完整 pair 滑动，并保留 tool-call/feedback 配对。

### 7.2 REPL 测试

- prose 澄清后输入路径时，第二次 provider 请求同时包含原始目标、问题与路径。
- 普通输入、`/single`、inline image、`/duo` 与 `/triad` 按设计更新会话。
- `/help`、`/model`、`/reload`、`/memory`、`/mcp` 与非法命令不更新会话。
- `/new` 与 `/reset` 不调用 provider，清空 transcript 与暂存图片，并保留模型与 usage。
- provider 消息数量从彼此独立的 `[2, 2]` 变为预期的增长序列。

### 7.3 安全与回归

- 第二个 restricted Task 即使继承批准文本也从 project scope 开始。
- 单次 CLI、Loop、HTTP、协作持久化、TaskOutcome 序列化和 cache accounting 保持兼容。
- 完整测试与受控多轮 REPL smoke 通过。

## 8. 实施顺序

1. 增加 Task/Step/context 失败测试并实现 transcript 传递。
2. 增加 Single REPL 连续性与重置命令。
3. 增加协作 prior context 与公开结果投影。
4. 运行专项测试、完整质量门禁和 smoke 验证。

本变更不增加依赖、模块注册层、持久化格式或摘要器。

