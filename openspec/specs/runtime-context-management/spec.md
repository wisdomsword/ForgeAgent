# runtime-context-management Specification

## Purpose
Define bounded context assembly, compaction, masking, and continuity rules for Task execution without changing tool or sandbox authority.
## Requirements
### Requirement: 共享且可配置的运行时上下文策略
系统 MUST 通过 Task 注入、Step 执行的共享 context policy 管理每次模型请求的消息视图。CLI 单次执行、REPL 和 HTTP 任务 MUST 使用同一策略语义；v1 MUST 只提供 sliding-window 实现，不得为未实现策略增加占位实现或插件注册层。

#### Scenario: 三种入口共享策略
- **WHEN** 相同模型能力、context 配置和消息历史分别通过 CLI、REPL 与 HTTP Task 执行
- **THEN** 三种入口提交给模型的有界消息视图遵循相同的窗口和工具反馈规则

#### Scenario: 旧配置缺少 context 字段
- **WHEN** 用户使用不包含 M17 context 字段的既有配置启动 ForgeAgent
- **THEN** 配置继续有效，并自动使用内置的有界 sliding-window 与 tool-result limit 默认值

#### Scenario: HTTP 客户端尝试覆盖策略
- **WHEN** HTTP 提交 body 包含 context policy、窗口、截断限额或其他服务端 context 配置
- **THEN** 请求按严格 schema 被拒绝，服务端执行策略不发生变化

### Requirement: Sliding window 产生有界且非破坏性的请求视图
系统 MUST 在每次模型调用前，依据模型 context window、本地近似 token 估算、最大输出预留和安全余量构造有界 request view。策略 MUST 保留 system prompt 和初始 goal，并只按完整交互单元淘汰较旧历史；它 MUST NOT 原地改写 Step 的真实 conversation、RoundResult 或 TaskOutcome。

#### Scenario: 未达到窗口阈值
- **WHEN** 当前 conversation 的估算用量未达到配置阈值
- **THEN** 发给模型的消息内容和顺序与未启用窗口处理时完全相同

#### Scenario: 超过窗口阈值
- **WHEN** 历史增长使估算用量超过配置阈值
- **THEN** request view 保留 system prompt、初始 goal 和最新完整交互单元，并从最旧的可淘汰单元开始移除直到进入预算

#### Scenario: ToolCall 与反馈保持配对
- **WHEN** 待淘汰边界附近包含 assistant ToolCall 及其后续 tool feedback
- **THEN** 策略保留或移除整个交互单元，不产生孤立 ToolCall 或孤立 feedback

#### Scenario: 不可淘汰的初始请求超过预算
- **WHEN** system prompt、初始 goal 与必要输出预留在首次 provider 调用前已经超过可用 context 预算
- **THEN** 系统不截断 system prompt 或 goal、不调用 provider，并以既有公开 `status=failed` 和有界的 context-budget detail 返回结构化任务失败

#### Scenario: 最新完整交互单元仍无法放入预算
- **WHEN** 不可淘汰前缀与最新一个完整 assistant-feedback 交互单元的估算用量仍超过可用 context 预算
- **THEN** 系统不拆分或改写该交互单元，并在创建下一次 LLM attempt 审计事件和调用 provider 之前以既有 `status=failed` 返回有界的 context-budget detail

#### Scenario: 近似估算仍未避免 provider 上限错误
- **WHEN** provider 因实际 tokenizer 差异仍返回 context-length 错误
- **THEN** 系统沿用结构化 ClientError 语义，不无限重试、不伪造完成，也不静默降低任务标准

### Requirement: 所有工具反馈使用统一且诚实的限额
系统 MUST 在工具反馈进入下一轮 user message 前，对成功和失败的所有 ToolOutcome 使用同一可配置近似 token 限额。截断标记 MUST 明确说明结果未完整、精确可得的原始字符或字节总量、当前展示范围，以及该工具真实支持的继续读取或缩小查询方法；系统 MUST NOT 虚构 cursor、offset、文件或可恢复能力。

#### Scenario: Exec stdout 超过限额
- **WHEN** 成功 Exec 的 stdout 超过配置限额
- **THEN** 下一轮反馈只包含有界片段和诚实截断标记，并给出可执行的分片或缩小输出方法

#### Scenario: 普通成功 detail 超过限额
- **WHEN** MCP、Survey、File、WebFetch 或其他成功工具的 detail 超过配置限额
- **THEN** 该 detail 与 Exec stdout、失败 detail 一样被统一限制，不再绕过 limiter

#### Scenario: 多个工具结果共享单轮预算
- **WHEN** 单轮包含多个 ToolOutcome，且完整 detail 合计超过单轮 feedback 总预算
- **THEN** limiter 按原始顺序保留每个 outcome 的状态头，在单结果上限内通过确定性水位分配公平限制 detail，并将短结果未使用的份额重新分配给仍有需求的结果

#### Scenario: 工具反馈固定元数据超过预算
- **WHEN** 所有 outcome 的状态头、必要截断标记和真实 continuation 的固定估算成本已经超过单轮 feedback 总预算
- **THEN** 系统保留 RoundResult 中全部原始 outcomes 和既有工具审计，不省略已执行工具状态、不调用 provider，并以既有 failed 终态和有界的 `feedback metadata exceeds context budget` detail 收敛

#### Scenario: 工具没有分页或持久结果
- **WHEN** 被截断的工具不支持 cursor、offset 或持久化完整结果
- **THEN** continuation 只说明真实可行的重跑或缩小输入方式，不暗示不存在的续读能力

#### Scenario: 本地结果保留真实执行事实
- **WHEN** 发给模型的工具反馈因 context 限额被截断
- **THEN** 原始 ToolOutcome、任务终态推导和既有安全结果投影不被截断后的 request 文本替换

### Requirement: Prompt-cache 稳定前缀得到保持和审计
系统 MUST 保持 system prompt 内身份、固定协议、项目内容和工具定义的既定顺序，并 MUST NOT 将时间、进度、cache 指标或其他逐轮动态数据插入稳定前缀。窗口处理 MUST 构造新的 request view，不改写仍被保留的历史消息。

#### Scenario: 阈值以下连续轮次
- **WHEN** 同一 Task 连续执行多轮且尚未触发 sliding window
- **THEN** 后续请求只追加新的 assistant 与 feedback 消息，已有稳定前缀保持逐字不变

#### Scenario: 窗口发生滑动
- **WHEN** 策略淘汰旧交互以满足预算
- **THEN** system prompt 仍位于首位且内容不变，所有保留消息的内容与相对顺序不被重写

#### Scenario: 排序审计
- **WHEN** M17 的 prompt-cache 排序验收运行
- **THEN** 验收能证明固定内容位于动态内容之前，并能检测动态状态误入 system 稳定前缀的回归

### Requirement: Cache hit rate 使用跨 provider 的统一语义
系统 MUST 在保留 provider 原始 TokenUsage 计数的同时获得 normalized total prompt token denominator。任务或会话的 cache hit rate MUST 按累计 cached tokens 除以累计 normalized total prompt tokens 计算，不得平均逐轮百分比。

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
- **WHEN** REPL 在同一会话中完成多个彼此独立的 goal
- **THEN** usage 行基于会话累计分子和分母显示 cache hit rate，但消息历史仍不跨 goal 继承

#### Scenario: 零分母
- **WHEN** 没有可用的 normalized prompt token 分母
- **THEN** CLI 显示 `cache_hit=n/a`，且计算过程不抛出除零错误

#### Scenario: HTTP usage projection 保持兼容
- **WHEN** HTTP 客户端查询 M17 执行后的任务结果
- **THEN** usage 响应仍只包含既有字段，不新增 cache hit rate 或内部 normalized denominator

### Requirement: M16 HTTP 安全与生命周期契约保持不变
系统 MUST 仅改变 HTTP Task 内部发送给模型的 request view，并 MUST 保持 M16 的 bearer 鉴权、严格请求 schema、server-owned 执行策略、协作式取消、安全结果投影、审计降级、task correlation 和精确 headless allowlist 行为。

#### Scenario: HTTP gated tool 执行
- **WHEN** HTTP Task 在 M17 context policy 下请求 MCP、WebFetch 或 FileWrite
- **THEN** 操作仍必须通过服务端精确 allowlist，且 MCP autoApprove 不能绕过该判断

#### Scenario: HTTP 任务取消
- **WHEN** 客户端取消正在使用 sliding-window request view 的任务
- **THEN** 任务仍在下一个安全边界按既有协作式取消语义收敛，不影响其他任务

#### Scenario: HTTP 终态查询
- **WHEN** 客户端查询已完成、失败、拒绝、需信息或取消的 M17 任务
- **THEN** 响应继续使用有界且脱敏的既有 status、reason、detail、round-count 和 usage 投影
