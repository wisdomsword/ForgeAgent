## Context

`Task.run()` 当前创建 system 与 goal 两条初始消息，`Step` 在本地 conversation 副本上逐轮追加 assistant 回复和 user feedback。该循环没有依据模型 `context_window` 的历史预算；工具反馈则只对 Exec stdout 和失败 detail 使用固定 4096 字符尾截断，成功的普通 tool detail 不受同一限制。

CLI 单次执行、REPL 和 HTTP 都通过 `Task` 进入同一 `Step` 循环，但装配方式不同：REPL 每个 goal 创建独立 Task，只复用会话级 model/identity/MCP/usage；HTTP 由服务端 factory 创建 Task，并额外持有取消事件、审计 sink、task id 和禁止 MCP autoApprove 的 headless 策略。M17 必须复用共享核心，不能在三个入口各自实现压缩。

模型能力表已经提供 `context_window` 和 `max_output_tokens`，但项目没有统一 tokenizer。已有 `TokenUsage` 还保留 provider 原始口径：OpenAI-compatible 的 input 通常包含 cached tokens，Anthropic 将普通 input、cache creation 和 cache read 分开报告，因此不能直接用同一个原始字段作跨 provider cache rate 分母。

## Goals / Non-Goals

**Goals:**

- 用一个最小策略边界为所有 Task 入口提供有界 conversation request view。
- v1 只实现 sliding window，并保持 system prompt、当前 goal 和被保留交互的内容与顺序不被改写。
- 统一所有工具反馈的限额、截断声明、原始总量和继续读取提示。
- 使用无网络、无新依赖的近似 token 估算，结合输出预留和安全余量触发窗口处理。
- 计算 provider-normalized cache hit rate，并在 CLI 与 `llm.outcome` 审计中使用同一语义。
- 对旧配置和阈值以下的普通任务保持兼容，同时维持 M16 HTTP 信任边界。

**Non-Goals:**

- 不实现 importance、summary 或 hybrid 策略，也不创建这些策略的占位实现或注册中心。
- 不做意图路由、压缩前后决策一致性评分、Memory 生命周期、checkpoint/resume 或 token stop policy。
- 不引入厂商 tokenizer、在线 token-count API 或新的运行时依赖。
- 不让 REPL 跨 goal 继承消息历史，不让 HTTP 请求覆盖服务端 context policy。
- 不改变 HTTP endpoint、请求 schema、usage 响应 schema、安全结果投影或 headless allowlist 语义。

## Decisions

### 1. Context policy 由 Task 注入，在 Step 请求边界执行

新增一个最小 `ContextPolicy` 契约和唯一的 `SlidingWindowContextPolicy` 实现。Task 接收已验证的 context 配置或显式注入的 policy，并转交 Step；Step 在每次调用 `complete()`/`stream()` 前根据当前 conversation 构造 request view。

策略不得原地修改 Step 持有的完整 conversation。RoundResult、任务完成判定、取消边界和审计 correlation 继续基于真实执行历史；只有发给模型的消息视图可以滑动。这使 CLI、REPL、HTTP 和测试直接构造的 Task 共享同一行为，也避免压缩副作用污染任务结果。

不为未来策略引入 factory、manager、plugin 或空子类。未来增加第二种真实策略时再扩展选择面。

### 2. Sliding window 保持稳定前缀和完整交互边界

system prompt 永远保持首位，初始 goal 不被静默删除。策略从旧到新移除历史，只保留完整的交互单元，禁止留下没有对应 tool feedback 的 assistant ToolCall，或没有对应 assistant 请求的孤立 feedback。

窗口尚未触发时，request message 列表的内容和顺序必须与当前行为相同。触发后不可避免会改变 provider 可缓存前缀；实现应只构造新的 request view，不改写仍被保留的 message，并避免把时间、进度或统计数据插入稳定 system 前缀。

保留单元的精确定义留给 Superpowers 技术设计裁决。若不可淘汰的 system prompt、初始 goal 与必要输出预留在首次模型调用前已经超过预算，Task 必须 fail-fast：不得截断 system/goal，不得调用 provider，并以既有公开 `status=failed` 和有界的 context-budget detail 收敛。这样无需新增 HTTP status/reason 字段，也不会把本地预算校验伪装成一次真实 provider attempt。

### 3. 近似 token 预算优先轻量与保守

估算完全在本地完成，输入包括 message 文本、多模态元数据的有界表示和固定 message framing 开销。触发预算以模型 `context_window` 为上限，先扣除最大输出预留，再应用安全余量。

估算只用于窗口保护，不用于计费或 cache 指标。允许因保守估算而提前压缩；不承诺替代 provider 的精确 tokenizer。若 provider 仍返回 context-length 错误，继续沿用结构化 `ClientError`，不得无限重试或静默降低完成标准。

估算公式、余量、默认阈值和中英文/代码/JSON/emoji 测试矩阵在技术设计中确定。

### 4. 工具反馈在单一渲染边界统一限额

移除按成功/失败分支不一致的固定字符截断，改为在 feedback 进入下一轮 user message前统一处理所有 ToolOutcome。限额使用与 context 配置一致的近似 token 单位；原始 ToolOutcome 和安全 Task 结果投影不因 request-view 截断而被替换。

截断标记至少包含：结果未完整、精确可得的原始字符或字节总量、当前展示范围，以及对该工具真实可执行的继续方式。实现不得虚构 cursor、offset 或可恢复文件；若工具只支持重跑或缩小查询，提示必须如实表达。

不同工具的 continuation 模板、是否需要扩展现有 FileRead 参数，以及无法分页的 MCP 结果如何诚实处理，留给技术设计裁决。任何工具协议扩展都必须在 design 审视时显式列出，不能在 build 阶段顺手扩大。

### 5. 配置缺失时启用有界默认值

新增一份集中验证的 context 配置，供 Task/Step、CLI/REPL 和 HTTP 服务端装配复用。旧配置没有 M17 字段时仍可加载，并得到内置 sliding-window 与 tool-result limit 默认值；不以“无限追加”作为兼容默认。

HTTP 的 policy 和限额只来自服务端装配，提交 body 仍只接受既有低风险字段。配置文件位置、字段名、数值范围、reload 行为和默认阈值在技术设计中根据现有 `config.yaml`/HTTP config 的不同生命周期确定。

### 6. Cache hit rate 使用统一分母，保留原始 usage

provider adapter 在不改变现有原始 `input_tokens`、`cached_tokens` 等值的前提下，提供 normalized total prompt token denominator：OpenAI-compatible 使用 total prompt tokens；Anthropic 使用普通 input、cache creation 与 cache read 的总和。

任务或会话汇总使用 `sum(cached_tokens) / sum(normalized_total_prompt_tokens)`，不得平均逐轮百分比。分母为零时 CLI 显示 `cache_hit=n/a`，审计写 JSON `null`。

CLI 在每个 Task 完成后的现有 usage 行展示；REPL 继续显示 session 累计值，不逐模型 round 刷新。`llm.outcome.parameters.usage` 保留原始计数，并新增同级 `cache_hit_rate`。HTTP 的 `_usage_summary` 字段集合保持不变。

normalized denominator 在内部结果模型中的具体承载方式由技术设计确定，但不得迫使 HTTP 暴露新字段或改变既有计数值。

### 7. M16 HTTP 契约作为回归边界

M17 只改变服务端 Task 的内部 request view。以下行为必须原样保持：所有任务路由的 bearer 鉴权、只接受 goal 的严格提交 schema、server-owned tier/root/identity/credentials、协作式取消、bounded safe result projection、审计降级、task correlation，以及 `allow_auto_approve=False` 下的精确 headless allowlist。

## Risks / Trade-offs

- **近似估算可能提前压缩或仍低估特殊输入** → 使用输出预留、安全余量和多语言/代码测试矩阵；保留 provider context error 的结构化失败语义。
- **不可淘汰的 system 与 goal 本身超过预算** → 首次 provider 调用前返回既有结构化 failed 终态，不静默截断用户目标，也不扩展 HTTP 公开 reason schema。
- **滑动窗口删除了后续决策依赖的早期细节** → 永久保留 system 与 goal，只按完整交互单元淘汰，并用长对话 mock replay 验证任务仍能完成；M17 不声称解决语义摘要问题。
- **统一截断后更多成功结果变短** → 阈值可配置，标记必须诚实并提供真实 continuation；完整 ToolOutcome 仍供本地结果与测试使用。
- **provider usage 口径继续变化** → 原始字段保持原样，normalized denominator 在 adapter 边界测试，不在 CLI 通过模型名分支。
- **压缩破坏部分 prompt-cache 命中** → 阈值以下保持纯追加；触发后仅移动 request window，不改写稳定 system prompt 和保留消息。
- **HTTP Task 装配遗漏 policy 或意外暴露新配置** → 增加 HTTP factory wiring 测试并完整回跑 M16 server/service/headless 契约测试。

## Migration Plan

1. 加入 context 配置与默认 policy，先证明阈值以下行为和旧配置兼容。
2. 在 Step request 边界接入 sliding request view，并用长对话 mock replay 验证。
3. 将所有 tool feedback 收敛到统一 limiter，补各 outcome 分支与 continuation 测试。
4. 在 provider usage 边界增加 normalized denominator，接入 CLI 与 audit 指标，但保持 HTTP projection 不变。
5. 完成 prompt 顺序审计、golden 回放、M16 HTTP 回归和全量验证。

回滚时可移除 M17 配置与 policy 注入，恢复原 Step request view；原始 TokenUsage、TaskOutcome 和 HTTP schema 均不需要数据迁移。

## Open Questions

- Sliding window 的最小保留单元是 assistant+feedback 对、完整 round，还是更严格的 tool-call/result 组？
- 本地 token 估算的公式、安全余量和默认触发阈值分别是多少？
- context 配置应扩展通用用户 config、使用独立文件，还是由 CLI 与 HTTP 各自装配同一模型？
- 每种工具的 continuation 文案是什么；FileRead 是否需要本 change 内新增 offset/limit，还是只允许模型通过 Exec/缩小输入继续？
- normalized total prompt denominator 应作为 TokenUsage 的排除序列化字段、RoundResult 派生值，还是独立内部 metrics 对象？
