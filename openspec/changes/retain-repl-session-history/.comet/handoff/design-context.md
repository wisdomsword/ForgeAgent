# Comet Design Handoff

- Change: retain-repl-session-history
- Phase: design
- Mode: compact
- Context hash: 3953f1b6f73427751157d2f21435cff50d7bfae222b120bfc43b188e1935f8ea

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/retain-repl-session-history/proposal.md

- Source: openspec/changes/retain-repl-session-history/proposal.md
- Lines: 1-28
- SHA256: 5cecdc4cb2a71830a051232418bb99df5a3139a40db824f40bc01901d1689da6

```md
## Why

当前 REPL 将每条 `forge>` 输入作为完全独立的 Task，后续输入只收到 system prompt 和当前文本。用户对上一轮澄清问题作答时，原始目标已经丢失，导致 Agent 重复询问、降级执行或把补充参数当成新任务。

## What Changes

- REPL 在进程内保留任务型输入、模型回复、工具调用和有界工具反馈，并把它们作为后续任务的会话上下文。
- 新增 `/new` 与 `/reset` 命令，清空模型会话历史和暂存图片，同时保留模型、sandbox、Memory、MCP 与进程级 usage 统计。
- 调整 sliding-window 的轮次校验和淘汰规则，使跨顶层输入的会话仍按完整交互单元保留或移除。
- 每条顶层输入仍创建新的 Task、backend、Runtime、task ID 和文件系统授权状态；历史文本不继承执行权限。
- 普通任务及显式 Single/Duo/Triad 任务的安全可见结果进入历史；管理类 slash command 不进入模型上下文。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `repl-interactive-input`: REPL 从输入行回放扩展为进程内模型会话连续性，并增加显式重置命令。
- `runtime-context-management`: 请求视图支持跨顶层输入的完整会话轮次，替换“REPL goal 消息历史互不继承”的旧要求。
- `task-filesystem-authority`: 明确会话历史不得继承上一 Task 的文件系统授权或执行状态。

## Impact

- 主要影响 `src/forgeagent/_cli_repl.py`、`src/forgeagent/cli.py`、`src/forgeagent/task.py`、`src/forgeagent/step.py`、`src/forgeagent/context.py` 及对应 CLI/Task/context 测试。
- 不新增依赖、不持久化会话、不改变单次 `run`、HTTP、Loop 的公开契约，也不放宽 sandbox 或工具审批边界。

```

## openspec/changes/retain-repl-session-history/design.md

- Source: openspec/changes/retain-repl-session-history/design.md
- Lines: 1-70
- SHA256: 2ee1f718245de3afc685f62ea0fe0d334642e01d0672222461d17a2d0e942fca

```md
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

```

## openspec/changes/retain-repl-session-history/tasks.md

- Source: openspec/changes/retain-repl-session-history/tasks.md
- Lines: 1-22
- SHA256: 562a2f2884749ea5b00622aa6171c928b97e3a4c8de47a1961679a1e53c2e94d

```md
## 1. 会话记录契约

- [ ] 1.1 增加先失败的 Task/context 测试，覆盖历史输入、刷新 system prompt、跨输入配对、有界滑动和序列化排除
- [ ] 1.2 实现 Task 会话记录输入输出，同时保持单次运行与 HTTP 结果契约

## 2. REPL 连续性

- [ ] 2.1 增加先失败的 REPL 测试，证明普通输入与显式 Single 输入继承此前任务消息
- [ ] 2.2 实现进程内 REPL 会话记录，并且只在产生任务的输入完成后更新
- [ ] 2.3 增加 Duo/Triad 安全可见结果投影的先失败测试与实现，不包含协作内部内容

## 3. 重置与授权边界

- [ ] 3.1 增加 `/new` 与 `/reset` 的命令表、帮助、清空会话、清空暂存图片、不调用 provider 和保留进程状态测试
- [ ] 3.2 实现 `/new` 与 `/reset`，并输出有界确认信息
- [ ] 3.3 增加回归测试，证明继承的授权文本不能恢复新 Task 的文件系统权限

## 4. 验证

- [ ] 4.1 运行 Task、context、CLI、协作、文件系统授权与 HTTP 专项测试
- [ ] 4.2 运行 lint、类型检查、完整测试、OpenSpec 严格校验和多轮 REPL smoke
- [ ] 4.3 审查 diff 中是否存在会话泄漏、过期 system prompt、无界历史或无关改动

```

## openspec/changes/retain-repl-session-history/specs/repl-interactive-input/spec.md

- Source: openspec/changes/retain-repl-session-history/specs/repl-interactive-input/spec.md
- Lines: 1-37
- SHA256: 8f86e5eed39a0a262ca942f3b58be0da8edb153ecb568b2f83bc7029ae2d5722

```md
## ADDED Requirements

### Requirement: REPL 模型会话在进程内连续

ForgeAgent SHALL 在同一 REPL 进程内保留任务型输入及其安全可见结果，并将该 transcript 作为后续任务型输入的模型上下文。历史 SHALL 保持结构化消息与工具调用配对，MUST NOT 跨进程持久化。每条顶层输入 MUST 继续创建新的 Task；管理类 slash command MUST NOT 写入模型 transcript。

#### Scenario: 澄清答案继续原任务
- **WHEN** 首条输入提出任务，模型通过 Survey 或 prose 请求必要信息，用户在下一条 `forge>` 输入中提供答案
- **THEN** 下一 Task 的模型请求同时包含原任务、澄清请求和用户答案，而不是把答案作为无上下文的新目标

#### Scenario: 普通任务连续引用
- **WHEN** 用户完成一项普通或显式 Single 任务后提交依赖上一结果的新输入
- **THEN** 后续模型请求包含上一任务的用户输入、模型回复、工具调用与有界反馈

#### Scenario: 协作任务只保留公开结果
- **WHEN** Duo 或 Triad 任务完成并返回用户可见结果
- **THEN** REPL 将原始 goal 与最终安全可见投影加入会话，但不加入 planner、evaluator 或未公开候选的内部内容

#### Scenario: 管理命令不污染会话
- **WHEN** 用户在两个任务型输入之间执行 `/help`、`/model`、`/reload` 或其他管理命令
- **THEN** 命令执行其既有功能，但命令文本与管理输出不进入后续模型请求

### Requirement: 用户可显式重置模型会话

REPL command table SHALL 提供 `/new` 与 `/reset`。任一命令 SHALL 清空进程内模型 transcript 与暂存图片，同时 MUST 保留当前模型、sandbox tier、Memory、MCP、输入行历史和进程累计 usage。清空操作 MUST NOT 启动 Task 或调用 provider。

#### Scenario: new 清空历史
- **WHEN** 用户在已有模型会话后提交 `/new`
- **THEN** 下一任务只使用新的 system prompt 和新输入，不包含重置前的 transcript

#### Scenario: reset 清空暂存图片
- **WHEN** 用户暂存图片并提交 `/reset`
- **THEN** transcript 与暂存图片均被清空，当前模型、sandbox、Memory、MCP 和累计 usage 保持不变

#### Scenario: 重置不调用模型
- **WHEN** 用户提交 `/new` 或 `/reset`
- **THEN** REPL 输出有界确认并返回提示符，不创建 Task、不调用 provider

```

## openspec/changes/retain-repl-session-history/specs/runtime-context-management/spec.md

- Source: openspec/changes/retain-repl-session-history/specs/runtime-context-management/spec.md
- Lines: 1-63
- SHA256: a12f2c1f65ee2f7ea3220c750d2372da12656c07c9cf372cd43003e0e98904fd

```md
## MODIFIED Requirements

### Requirement: Sliding window 产生有界且非破坏性的请求视图
系统 MUST 在每次模型调用前，依据模型 context window、本地近似 token 估算、最大输出预留和安全余量构造有界 request view。策略 MUST 保留当前 system prompt 和会话首个 user 锚点，并只按完整交互单元淘汰较旧历史；跨顶层 REPL 输入的 transcript MUST 通过同一轮次配对校验。策略 MUST NOT 原地改写 Step 的真实 conversation、RoundResult 或 TaskOutcome。

#### Scenario: 未达到窗口阈值
- **WHEN** 当前 conversation 的估算用量未达到配置阈值
- **THEN** 发给模型的消息内容和顺序与未启用窗口处理时完全相同

#### Scenario: 超过窗口阈值
- **WHEN** 跨一个或多个顶层输入的历史增长使估算用量超过配置阈值
- **THEN** request view 保留当前 system prompt、首个 user 锚点和最新完整交互单元，并从最旧的可淘汰单元开始移除直到进入预算

#### Scenario: ToolCall 与反馈保持配对
- **WHEN** 待淘汰边界附近包含 assistant ToolCall 及其后续 tool feedback
- **THEN** 策略保留或移除整个交互单元，不产生孤立 ToolCall 或孤立 feedback

#### Scenario: 顶层输入保持轮次配对
- **WHEN** 一个已完成 Task 的 transcript 以 assistant 结束，REPL 为下一 Task 追加新的 user 输入
- **THEN** context policy 将其视为合法的下一完整交互边界，并继续按 assistant/user 单元验证和淘汰

#### Scenario: 不可淘汰的初始请求超过预算
- **WHEN** system prompt、会话首个 user 锚点与必要输出预留在 provider 调用前已经超过可用 context 预算
- **THEN** 系统不截断 system prompt 或 user 锚点、不调用 provider，并以既有公开 `status=failed` 和有界的 context-budget detail 返回结构化任务失败

#### Scenario: 最新完整交互单元仍无法放入预算
- **WHEN** 不可淘汰前缀与最新一个完整 assistant/user 交互单元的估算用量仍超过可用 context 预算
- **THEN** 系统不拆分或改写该交互单元，并在创建下一次 LLM attempt 审计事件和调用 provider 之前以既有 `status=failed` 返回有界的 context-budget detail

#### Scenario: 近似估算仍未避免 provider 上限错误
- **WHEN** provider 因实际 tokenizer 差异仍返回 context-length 错误
- **THEN** 系统沿用结构化 ClientError 语义，不无限重试、不伪造完成，也不静默降低任务标准

### Requirement: Cache hit rate 使用跨 provider 的统一语义
系统 MUST 在保留 provider 原始 TokenUsage 计数的同时获得 normalized total prompt token denominator。任务或会话的 cache hit rate MUST 按累计 cached tokens 除以累计 normalized total prompt tokens 计算，不得平均逐轮百分比。REPL 的消息 transcript SHALL 跨任务型输入继承，usage 仍按进程累计且不因 `/new` 或 `/reset` 清零。

#### Scenario: OpenAI-compatible usage
- **WHEN** provider 报告 total prompt tokens 和其中的 cached tokens
- **THEN** normalized denominator 使用 provider 的 total prompt token 口径，原始 input/cached 字段保持不变

#### Scenario: Anthropic usage
- **WHEN** provider 分别报告普通 input、cache creation 和 cache read tokens
- **THEN** normalized denominator 包含三者总量，原始 input/cached 字段保持不变

#### Scenario: CLI 单次任务输出
- **WHEN** 一个 CLI Task 完成并汇总了非零 normalized prompt tokens
- **THEN** 现有最终 usage 状态行显示该 Task 的累计 cache hit rate，而不是逐模型 round 输出

#### Scenario: REPL 会话累计
- **WHEN** REPL 在同一进程中完成多个连续任务型输入
- **THEN** 后续输入继承模型 transcript，usage 行基于进程累计分子和分母显示 cache hit rate

#### Scenario: 重置不清空 usage
- **WHEN** 用户在 REPL 中执行 `/new` 或 `/reset`
- **THEN** 模型 transcript 被清空，但 cache hit rate 的累计分子和分母保持不变

#### Scenario: 零分母
- **WHEN** 没有可用的 normalized prompt token 分母
- **THEN** CLI 显示 `cache_hit=n/a`，且计算过程不抛出除零错误

#### Scenario: HTTP usage projection 保持兼容
- **WHEN** HTTP 客户端查询执行后的任务结果
- **THEN** usage 响应仍只包含既有字段，不新增 cache hit rate、内部 normalized denominator 或 REPL transcript

```

## openspec/changes/retain-repl-session-history/specs/task-filesystem-authority/spec.md

- Source: openspec/changes/retain-repl-session-history/specs/task-filesystem-authority/spec.md
- Lines: 1-36
- SHA256: f75aa10d325d408874a7749a2a674bda5c5b6970bc6dadab826179b454d14e07

```md
## MODIFIED Requirements

### Requirement: Restricted tasks can receive one task-scoped full-disk filesystem grant
ForgeAgent SHALL expose a typed `RequestFilesystemAccess` tool in the default task registry. In `restricted` tier, a successful interactive confirmation MUST expand Python execution and built-in file tools to the current platform filesystem root for the remainder of that Task while preserving the restricted subprocess, environment scrubbing, resource limits and network denial. The grant MUST NOT persist, cross into a later REPL input, be reconstructed from conversation history, or change the tier label to trusted.

#### Scenario: Restricted user approves full-disk access
- **WHEN** a restricted task requests full-disk filesystem access through `RequestFilesystemAccess` and the terminal user approves
- **THEN** subsequent Exec and built-in file calls in that Task can access paths outside the project root and the sandbox tier remains restricted

#### Scenario: Approved task does not prompt twice
- **WHEN** `RequestFilesystemAccess` is called again after the same Task already received the grant
- **THEN** ForgeAgent reports that full-disk filesystem access is already active without invoking the confirmer again

#### Scenario: Grant does not approve later side effects
- **WHEN** a restricted Task receives a full-disk filesystem grant and then calls FileWrite, WebFetch or MCP
- **THEN** each later side-effecting operation still follows its own confirmation or receipt policy and cannot reuse the filesystem grant as approval

#### Scenario: Grant expires with the task
- **WHEN** an approved restricted Task ends and the REPL starts a new task-producing input with inherited transcript
- **THEN** the new Task starts project-scoped and requires its own full-disk confirmation for project-external access

#### Scenario: 历史授权文本不恢复权限
- **WHEN** 新 Task 的模型上下文包含上一 Task 的授权批准文本或成功工具反馈
- **THEN** 新 Task 的 backend、Runtime 和内置文件工具仍从未授权状态开始，宿主不会把历史文本解释为当前授权

#### Scenario: User rejects full-disk access
- **WHEN** the terminal user rejects `RequestFilesystemAccess`
- **THEN** ForgeAgent returns structured denial feedback and leaves both the backend and built-in file tools project-scoped

#### Scenario: Rejected task does not prompt twice
- **WHEN** `RequestFilesystemAccess` is called again after the same Task already received a rejection
- **THEN** ForgeAgent returns the prior denied state without invoking the confirmer again

#### Scenario: No confirmation channel is available
- **WHEN** a restricted task requests full-disk access without an interactive confirmation channel
- **THEN** ForgeAgent records a denied task decision and rejects the request deterministically without changing filesystem authority or waiting for input

```
