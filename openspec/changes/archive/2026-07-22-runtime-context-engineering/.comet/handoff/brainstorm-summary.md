# Brainstorm Summary

- Change: runtime-context-engineering
- Date: 2026-07-22
- Status: 技术方案已确认，等待写入最终 Design Doc

## 已确认事实与约束

- OpenSpec 是需求事实源；M17 只实现 sliding window，不实现或占位 importance/summary/hybrid。
- `Task.run()` 构造 system + goal；`Step._run_rounds()` 在本地副本上追加 assistant 与 feedback。CLI、REPL、HTTP 最终都构造 Task。
- REPL 每个 goal 创建独立 Task，只复用 model、identity、MCP 与 session usage；M17 不增加跨 goal 对话历史。
- 当前 4096 字符限制仅覆盖 Exec stdout 与失败 detail；普通成功 detail 会绕过。
- 初始 system + goal + 输出预留已经超预算时，首次 provider 调用前以既有 `status=failed` 和有界 context-budget detail 收敛；不截断 system/goal，不新增 HTTP reason/schema。
- 原始 TokenUsage 值和 HTTP usage projection 保持不变；cache rate 使用 provider-normalized total prompt denominator，零分母为 CLI `n/a` / audit JSON null。
- HTTP 继续保持 bearer 鉴权、严格 goal schema、server-owned policy、协作取消、安全结果投影、审计降级、task correlation 和 `allow_auto_approve=False` 精确 allowlist。
- 不新增 tokenizer 或其他运行时依赖，不调用在线 token-count API。

## 代码与参考实现发现

- agent 的 `ContextManager`/factory/四策略枚举、原地压缩、固定消息数保留和 `len(content)//4` 估算不适合直接复用；ForgeAgent 只借鉴最小策略边界。
- ForgeAgent `Message` 支持文本或多模态内容；估算器必须避免把 base64 图片数据当文本 token 原样计数。
- WebFetch 已把最多 1 MiB 内容落盘并只返回 2048 字符 preview；FileRead/FileList 没有分页参数，MCP continuation 取决于外部 tool schema。
- `TokenUsage` 是所有 client/round/CLI 的共享对象；HTTP usage summary 显式枚举四个既有字段。最小承载方式是在 TokenUsage 增加排除序列化的 normalized denominator 字段。
- `~/.forgeagent/config.yaml` 已同时被 model registry 和 web search 独立读取；model registry 只消费 `groups`，因此独立 context loader 不需要改变 provider routing schema。

## 已确认的技术方案

- 整体采用独立 `context.py` 的函数式核心，模块顺序为 ContextConfig → token estimator 纯函数 → ContextPolicy Protocol → SlidingWindowContextPolicy → feedback limiter 纯函数。policy 不持有 conversation；Step 仍是 convo/rounds 唯一事实源。
- Task 正常路径显式传入已构造 policy；直接构造 Step 的兼容路径允许 `context_policy=None`，但必须在 `Step.__init__` 立即按 client capability、params 和默认 ContextConfig 构造，禁止推迟到 `_run_rounds` 懒加载。
- Sliding window 的原子保留单元是完整 round：system 与 initial goal 是不可淘汰前缀；其余历史以 `[assistant, 紧随其后的 feedback 或 prose nudge]` 成组，从最旧 round 开始淘汰。单轮多个工具结果仍属于同一 feedback，不做消息级装箱或 ToolCall 级拆分。
- Context 配置复用 `~/.forgeagent/config.yaml` 的顶层 `context` mapping，由独立 `load_context_config()` 验证；model registry 继续只读取 `groups`，`/reload` 同步刷新 context。HTTP 的显式 serve 配置接受同结构的 `context` mapping，但客户端提交 body 不可覆盖，policy 始终由服务端所有。
- Token estimator 使用零依赖的字符类别加权启发式：ASCII 字母/数字/空白按约 4 chars/token，ASCII 标点按约 2 chars/token，非 ASCII 按 UTF-8 bytes/2，另加固定 message framing；图片使用固定且可配置的 token reserve，不把 base64 当作文本估算。
- 每次请求的估算输入预算为 `floor(capability.context_window * 0.8) - effective_max_output_tokens`；0.8 是可配置安全利用率。`O` 精确取 `params.max_output_tokens`（存在且非 None）否则取 `capability.max_output_tokens`，与 client wire 语义一致。若计算预算 `<= 0`，SlidingWindowContextPolicy 初始化立即因无可用输入预算 fail-fast；若正预算仍不足以容纳不可淘汰前缀，则 Task 在首次 provider 调用前 failed。
- 工具反馈使用双层限额：每个 ToolOutcome detail 和单轮合并 feedback 都有近似 token 上限。多工具时保留每个状态头，并在总预算内公平分配 detail，不允许一个结果挤掉其他结果状态。固定 2048/8192 没有 benchmark 依据，最终采用基于 input budget 的自适应默认值。
- `ToolOutcome` 新增 `continuation: str | None = None`。每个 Tool 在完整执行结束后按自身真实能力填写；Step limiter 只在 detail 实际截断时把 continuation 放入标记，未截断时忽略。MCP 使用固定诚实措辞：“此工具不保留游标；如需更多结果，请缩小查询参数后重新调用”，不得暗示通用分页能力。continuation 经过既有脱敏且不进入 HTTP 安全投影。
- `ToolOutcome` 新增 `truncation_mode: Literal["head", "tail"] = "tail"`，由 Tool 在产生 outcome 时按输出语义设置。Exec 使用默认 tail；FileRead、FileList、WebFetch、Survey 和 MCP 设置 head；Step limiter 仅执行字段值，不按工具名分支。该字段不进入 HTTP 投影。
- `TokenUsage` 新增内部字段 `total_prompt_tokens: int | None = Field(default=None, exclude=True, repr=False)`。Anthropic adapter 写 `input_tokens + cached_tokens`，OpenAI-compatible adapter 写 provider total input；Step 不含 provider 分支。成功 AssistantMessage 的 adapter 测试必须断言该值非 None。task/session 只要任一成功调用缺少 denominator，整体 cache rate 即为 `n/a`，不展示部分样本比率。
- Context 配置在 load 时通过 Pydantic 约束和跨字段检查一次性完整验证；Task 只接收已验证对象。CLI/REPL 启动遇到存在但无效的 `context` mapping 时返回结构化配置错误，HTTP serve 复用既有 `HttpStartupError`，不新增错误类型。缺少整个 mapping 使用默认值。`/reload` 对 model registry + context 做事务化验证和整体替换，任一失败即保留上一份全部有效配置。
- 公开配置面只含四个字段：`utilization_ratio: 0.8`、`image_token_reserve: 4096`、`tool_result_max_tokens: int | None = None`、`round_feedback_max_tokens: int | None = None`。后三者单位均为“近似 token 数”；image reserve 必须为正，两个可选 override 提供时必须为正。不暴露 estimator 字符权重、message framing 或只有一个合法值的 strategy。
- Feedback 缺省上限在 SlidingWindowContextPolicy 初始化时按固化 input budget 自适应计算：round = `floor(input_budget * 0.10)`，单结果 = `floor(round * 0.25)`。GenerationParams 在 Task 生命周期内不变，因此只计算一次。load-time 仅在两个字段都显式时检查 round >= result；policy 解析 null/override 后始终检查最终值为正且 round >= result，失败即 fail-fast，不做钳制。
- Feedback override 无论是双显式还是一个显式/一个 null，都先解析为两个最终整数，再统一验证 `round_limit > 0`、`result_limit > 0` 和 `round_limit >= result_limit`；自适应 floor 得到 0 与其他无效预算使用同一初始化失败语义。
- 单轮多 outcome 使用确定性水位分配：先按同一 estimator 扣除实际状态头、必要截断标记、真实 continuation 和极小数字变化余量的成本；每个 detail 不超过 policy 解析后的单结果上限，剩余 detail 预算在未满足项之间均分，短项余量继续分给长项。所有 outcome 状态头必须出现，原始 outcomes 顺序和内容不变。
- Outcome payload 除 stdout/detail 外还包含现有 static-analysis feedback 与 `exec_result.dropped_state_keys` 警告；后者表示 restricted executor 丢弃了无法跨进程序列化的 runtime state key，不是 Survey needs_info。两者都参与单结果与 round 总预算估算。
- 若所有状态头、必要截断标记和 continuation 的固定成本本身超过最终 round feedback 上限，不丢弃状态或放宽预算：当前 RoundResult 保留全部 outcomes 和既有工具审计，设置 `stopped_reason=Termination.FAILED` 与有界 `stopped_detail="feedback metadata exceeds context budget"`，并在构造下一轮 feedback/provider request 前停止，不新增 termination 枚举。

## 运行时数据流与调用时序

- `ContextPolicy.request_view(convo)` 由 Step 在每次 provider `complete`/`stream` 调用前调用一次；返回新 list，不原地修改完整 conversation。
- 每轮 context request view 构造及其本地 fail-fast 检查必须位于 operation id 创建和 `llm.attempt started` 审计之前；失败路径不得留下没有对应 outcome 的孤立 LLM attempt 事件。
- Step 的完整 conversation 追加的是 limiter 生成的有界 feedback Message，而不是原始 ToolOutcome detail；后续 sliding window 对这些已有限额的历史消息估算与淘汰。完整 ToolOutcome 仅保留在 RoundResult.outcomes，供本地结果、终态推导和测试使用；既有工具审计保留执行状态/correlation，不新增敏感 detail 复制。

## 关键取舍与风险

- 近似估算可能提前压缩或仍低估特殊输入；通过安全余量、多语言/代码/emoji 测试和 provider error 结构化失败缓解。
- Sliding window 会丢失旧细节；M17 不做摘要，只保证完整单元和长对话 mock 仍完成。
- MCP 或目录列表可能没有真实分页能力；continuation 必须承认限制，不能虚构 cursor。
- 在共享 config.yaml 增加 context 可减少文件面；必须通过回归证明 model registry 继续忽略非 groups 字段，`/reload` 原子地保留旧有效 registry/context 或采用新有效组合。

## 测试策略

- 纯函数表驱动：文本/多模态估算、预算边界、完整单元选择、输入不变性、超预算 fail-fast。
- Step/Task：complete 与 stream 共用 request view，所有 ToolOutcome 分支统一限额，原始 outcome 不变。
- Provider/usage：Anthropic 与 OpenAI-compatible normalized denominator、累计比率、零分母、序列化排除。
- CLI/REPL/HTTP：配置装配、session ratio、HTTP schema 快照、取消与 allowlist 回归。
- 长对话 mock replay、离线 golden、全量 pytest、Ruff、OpenSpec strict 与 diff check。

## Spec Patch

- 已在 open review 阶段补充“不可淘汰的初始请求超过预算”场景。
- 补充“不可淘汰前缀与最新完整 round 合计仍超过预算时，在下一次 LLM attempt 前失败”场景。
- 补充“单轮多个 ToolOutcome 合计超过 feedback 总预算时，保留全部状态头并公平限制 detail”场景。
- 补充“状态头、截断标记与 continuation 固定成本已超过 round 上限时，保留 outcomes 并结构化失败”场景。
