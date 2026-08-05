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
