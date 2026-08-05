## Context

ForgeAgent 的 REPL 目前只复用模型、MCP、Memory 和累计 usage。每次普通输入都会调用 `run_once()` 创建新的 `Task`，而 `Task.run()` 只组装当前 system prompt 与当前 goal。因此用户回答上一轮的澄清问题时，模型看不到原始目标。

会话连续性不能通过复用旧 `Task` 实现：Task 持有 task ID、backend、文件系统授权和确认状态，这些安全状态必须按顶层输入重新创建。旧 system prompt 也不能进入下一 Task，因为模型、身份和 Runtime Authority 可能已经通过 `/model` 或 `/reload` 改变。

## Goals / Non-Goals

**Goals**

- 同一 REPL 进程中，后续任务型输入能够看到此前的用户输入、模型输出和有界工具反馈。
- 每条顶层输入仍使用新 Task，并重新计算 system prompt 和全部 task-scoped authority。
- sliding window 能验证并按完整 `assistant -> user feedback/current input` 单元淘汰跨顶层输入的历史。
- `/new` 与 `/reset` 提供明确、可测试的会话清空边界。
- Single、Duo、Triad 都向会话留下用户可见且脱敏的结果，管理命令不污染模型上下文。

**Non-Goals**

- 不跨进程持久化会话。
- 不复用 Task、backend、Runtime、授权、确认结果或 task ID。
- 不改变单次 `run`、HTTP 或 Loop 的消息契约。
- 不保存协作模式的 evaluator 内部意见、未公开候选或原始审计记录。

## Decisions

### 1. REPL 持有不含 system prompt 的进程内 transcript

`_cli_repl` 持有一份 `Message` 序列。普通和显式 Single 任务把它交给 `run_once()`；`Task.run()` 每次先生成新的 system prompt，再按 `system + prior transcript + current user` 组装真实 conversation。任务结束后，REPL 取回去掉 system prompt 的最终 transcript。

选择该方案而不是复用 Task，是为了保持 task-scoped 安全边界；选择结构化 `Message` 而不是拼接自然语言摘要，是为了保留 provider tool-call 配对并让 context policy 对真实消息工作。

TaskOutcome 中用于 REPL 回传的 transcript 必须排除在公开序列化之外，避免扩大 HTTP 或日志结果面。

### 2. 顶层输入之间保持 provider 合法配对

会话 transcript 以首条 user message 为锚点，之后由完整的 assistant/user 单元组成；一项已完成任务以 assistant 结束，下一条顶层输入追加为 user。context policy 继续保留首个 user 锚点，并只移除完整单元，绝不制造孤立 tool call 或 tool feedback。

当不可淘汰前缀或最新完整单元超出预算时，沿用现有结构化失败语义，不静默截断 goal、system prompt 或消息内部内容。

### 3. 安全状态不进入会话继承

每条顶层输入继续创建新的 `Task`、backend、Runtime 和 task ID。历史中即使出现上一轮批准文本或 `RequestFilesystemAccess` 结果，也只是模型上下文，不能初始化新 Task 的授权或确认状态。新 Task 的 Runtime Authority 以本轮宿主状态重新生成。

### 4. 会话控制命令采用显式清空语义

`/new` 与 `/reset` 都清空模型 transcript 和暂存图片；模型选择、sandbox tier、已加载 Memory/MCP、输入行历史和进程累计 usage 保持不变。命令本身及 `/help`、`/model`、`/reload` 等管理命令不写入模型 transcript。

### 5. 协作模式只记录公开投影

Single 使用实际 Task transcript。Duo/Triad 在协作完成后写入原始用户 goal 与已经展示给用户的最终安全投影，不写入 planner/evaluator 内部对话、候选工件全文或隐藏反馈。这样后续输入能引用协作结果，又不扩大内部数据面。

## Risks / Trade-offs

- **历史增加 token 成本。** 由现有 sliding window 限制，且 usage 继续按进程累计显示。
- **模型可能把旧授权文本误当成当前授权。** 每轮 fresh system prompt 明确当前 Runtime Authority；工具实际授权仍由宿主检查，测试覆盖授权不会跨 Task。
- **TaskOutcome 增加内部字段可能意外外泄。** 字段默认排除序列化，并用 HTTP/模型 dump 回归测试锁定。
- **Duo/Triad 缺少完整 provider transcript。** 只记录用户可见投影，牺牲内部推理连续性以保持既有协作隔离。

## Migration Plan

1. 先增加 transcript 组装、返回与 context pairing 的失败测试。
2. 接入普通/Single REPL，再接入 Duo/Triad 的安全结果投影。
3. 增加 `/new`、`/reset` 并更新命令表、help 和输入测试。
4. 运行 Task、context、CLI、协作与 HTTP 回归。

本变更无磁盘数据迁移；退出进程会自然丢弃会话。

## Open Questions

无。跨进程持久化和会话摘要均明确排除在本变更之外。
