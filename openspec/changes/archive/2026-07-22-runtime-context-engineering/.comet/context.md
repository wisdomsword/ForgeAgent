# Comet Design Handoff

- Change: runtime-context-engineering
- Phase: design
- Mode: compact
- Context hash: 19e2b6443ee0727747b8064779b3c1ff85f90e292282859e68d7f9f97214fbae

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/runtime-context-engineering/proposal.md

- Source: openspec/changes/runtime-context-engineering/proposal.md
- Lines: 1-29
- SHA256: 1e46fd8e8d58711a4e1a6407395c9e5df65d046c0d0d065174577eaafd111655

```md
## Why

ForgeAgent 的 `Step` 目前持续追加完整对话，工具反馈又只对部分路径使用无实测依据的 4096 字符尾截断；长任务因此可能耗尽模型上下文，并让模型把不完整结果误认为完整结果。M17 需要在 M21 长任务循环之前补齐统一、有界、可观测的上下文工程能力，同时保持 M16 的 HTTP 安全契约。

## What Changes

- 新增最小可插拔的 context policy 接口，并提供唯一的 sliding-window 实现；`Task` 注入配置，`Step` 在每次模型调用前应用策略。
- 使用本地、确定性、模型无关的近似 token 估算与安全余量限制历史窗口；允许保守地提前压缩，不增加 tokenizer 依赖或厂商调用。
- 统一所有工具反馈的可配置近似 token 限额；截断内容必须明确标注未完整、原始总量和可执行的继续读取方法。
- 审计 system prompt、工具定义和规则的稳定前缀顺序，并保证窗口处理不改写保留消息或破坏完整交互单元。
- 基于 provider-normalized total prompt denominator 计算 cache hit rate；CLI 在现有 task/session usage 行展示，`llm.outcome` 审计事件记录相同指标。
- 保持原始 `TokenUsage` 计数字段、HTTP usage 响应 schema、REPL 不跨 goal 保留历史的语义，以及 M16 的鉴权、安全结果投影、取消、审计降级和精确 headless allowlist 契约。
- 旧配置缺少 M17 字段时继续有效，并启用内置的有界安全默认值；阈值以下的普通任务保持现有消息行为。

## Capabilities

### New Capabilities

- `runtime-context-management`: 定义运行时 sliding-window 压缩、统一工具反馈截断、稳定 prompt-cache 前缀和跨 CLI/REPL/HTTP 的 cache hit rate 可观测性。

### Modified Capabilities

- `audit-logging`: `llm.outcome` 在保留原始 usage 计数的同时记录 normalized cache hit rate，并为零分母使用安全的空值语义。

## Impact

- 主要影响 `Task`/`Step` 消息循环、模型 usage 归一化、CLI usage 状态行、HTTP 服务端 `Task` 装配和核心审计事件。
- 新增 context 配置加载与策略模块，并更新相关文档、mock replay、golden、CLI、审计和 M16 HTTP 回归测试。
- 不新增运行时依赖，不调用厂商 tokenizer，不改变 HTTP endpoint 或响应 schema，不引入 importance/summary/hybrid、Memory、checkpoint 或 token stop policy。

```

## openspec/changes/runtime-context-engineering/design.md

- Source: openspec/changes/runtime-context-engineering/design.md
- Lines: 1-108
- SHA256: f1651e0d29f110f7b0242ad69dc213092bd533f81710f5c0a82ed6c0e21a7a3c

[TRUNCATED]

```md
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

```

Full source: openspec/changes/runtime-context-engineering/design.md

## openspec/changes/runtime-context-engineering/tasks.md

- Source: openspec/changes/runtime-context-engineering/tasks.md
- Lines: 1-35
- SHA256: 1f49a83961e261902263c68d26c6193244dfbb3a3f46cadb2c68ed354e1e988d

```md
## 1. Context 配置与估算基础

- [ ] 1.1 完成 Superpowers 技术设计，裁决窗口交互单元、估算公式与安全余量、配置 schema/default、continuation 规则和 normalized denominator 承载方式
- [ ] 1.2 实现集中验证的 context 配置及旧配置缺失字段兼容测试，确保 CLI/REPL 与 HTTP 服务端装配使用同一语义
- [ ] 1.3 实现无外部依赖的本地近似 token 估算，并覆盖中英文、代码、JSON、emoji、多模态元数据和 message framing 边界

## 2. Sliding-window Context Policy

- [ ] 2.1 实现最小 ContextPolicy 契约和唯一 SlidingWindowContextPolicy，不增加未使用的策略占位、registry 或 factory
- [ ] 2.2 将 policy 从 Task 注入 Step，并在每次 complete/stream 调用前构造非破坏性的有界 request view
- [ ] 2.3 覆盖阈值以下完全兼容、system/goal 保留、首次调用前不可淘汰请求超预算的 fail-fast、完整交互单元淘汰、ToolCall/feedback 配对和 provider context error 语义

## 3. 统一工具反馈限额

- [ ] 3.1 用统一的可配置 limiter 替换固定 4096 字符分支逻辑，覆盖成功/失败 Exec、MCP、Survey、File、WebFetch 和其他 ToolOutcome
- [ ] 3.2 为每种工具实现诚实的截断标记、原始总量、展示范围与真实 continuation，并验证不会虚构分页或持久结果
- [ ] 3.3 验证 request feedback 截断不改写原始 ToolOutcome、任务终态、CLI 本地结果或 HTTP 安全投影

## 4. Cache 指标与审计

- [ ] 4.1 在 Anthropic 与 OpenAI-compatible adapter 边界提供 normalized total prompt denominator，同时保持既有原始 TokenUsage 值
- [ ] 4.2 在 CLI 最终 task/session usage 行增加累计 cache hit rate，并覆盖零分母 `n/a` 与 REPL 不跨 goal 继承历史
- [ ] 4.3 在成功 `llm.outcome` 中增加同语义 `cache_hit_rate`，覆盖数值、JSON null、掩码、序列化失败和 audit_degraded 回归
- [ ] 4.4 验证 HTTP usage 响应 schema 不暴露 cache hit rate 或内部 denominator

## 5. Prompt-cache 顺序与跨入口回归

- [ ] 5.1 增加稳定 system 前缀与动态尾部排序审计，验证阈值以下纯追加及窗口滑动后保留消息不被改写
- [ ] 5.2 增加 CLI、REPL、HTTP Task factory 的 policy wiring 测试，并完整回跑 M16 鉴权、严格 schema、取消、安全投影、审计和 exact allowlist 契约

## 6. 长任务验收与文档

- [ ] 6.1 增加超过窗口的长对话 mock replay，验证压缩后任务仍完成且截断协议文本可观察
- [ ] 6.2 更新配置、CLI usage、审计格式、上下文限制和威胁模型文档，并明确近似估算与 sliding window 的已知权衡
- [ ] 6.3 运行聚焦测试、完整 pytest、Ruff、离线 golden、OpenSpec strict validation 和 diff check，记录 M17 验证证据

```

## openspec/changes/runtime-context-engineering/specs/audit-logging/spec.md

- Source: openspec/changes/runtime-context-engineering/specs/audit-logging/spec.md
- Lines: 1-20
- SHA256: d73b7bff2eed7fd21d32aaf1fd0f5a835a4f71b24915fac52e6eeeb9383c2305

```md
## ADDED Requirements

### Requirement: LLM outcome 记录 normalized cache hit rate
每个成功的 `llm.outcome` 审计事件 MUST 在保留既有原始 usage 计数的同时记录使用统一 total prompt denominator 计算的 `cache_hit_rate`。该指标 MUST 与 CLI 的计算语义一致，不得包含 prompt、工具参数、文件内容或其他新增敏感数据。

#### Scenario: 有可用分母的成功调用
- **WHEN** 一个成功 LLM 调用返回 cached tokens 和非零 normalized total prompt tokens
- **THEN** `llm.outcome.parameters.usage` 保留原始计数，且同级 `cache_hit_rate` 写入 0 到 1 范围内的数值

#### Scenario: 零分母或 provider 未报告 usage
- **WHEN** normalized total prompt token 分母为零或不可获得
- **THEN** `llm.outcome.parameters.cache_hit_rate` 写入 JSON `null`，审计序列化继续成功

#### Scenario: Provider 原始口径不同
- **WHEN** Anthropic 与 OpenAI-compatible 对等调用分别产生 usage
- **THEN** 两类事件使用各自 adapter 提供的 normalized denominator，而不是在审计层按模型名称猜测口径

#### Scenario: 审计写入降级
- **WHEN** 包含 cache hit rate 的审计事件写入失败
- **THEN** 任务执行继续遵循既有 fail-open 和 `audit_degraded` 语义，不因新增指标改变任务结果

```

## openspec/changes/runtime-context-engineering/specs/runtime-context-management/spec.md

- Source: openspec/changes/runtime-context-engineering/specs/runtime-context-management/spec.md
- Lines: 1-127
- SHA256: dc16a292ec2ee9fdc75e3fd105ff169f87ce6255c592d50b1bee5e9760c88376

[TRUNCATED]

```md
## ADDED Requirements

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

```

Full source: openspec/changes/runtime-context-engineering/specs/runtime-context-management/spec.md
