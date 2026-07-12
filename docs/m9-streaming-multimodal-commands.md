# M9 设计草稿：流式支持 + 多模态消息 + 内嵌指令

> 状态：已评审（2026-07-12 用户裁决 8 项全部通过 + 7 项补充修订，见 §五/§九）。进 Phase 0 spike。
> 对应 ACTION_PLAN §四 M9 行：**流式支持**（`ModelClient.stream()` + `StreamEvent`）；**多模态消息**（`ContentItem`/`TextItem`/`ImageItem` 联合类型）；内嵌指令 `/model`（列出+切换）、`/search`（搜索网络资源）、`/mcp`（显示可用 MCP 服务及用法）、`/help`（命令帮助）；golden 任务集适量扩展。
> 前置：M10 已完成（`TokenUsage.cached_tokens`、WebFetch/SSRF Guard、File 工具、CLI 用量状态行均已就位）。

## 一、结论先行

三个正交增量，互不依赖，可并行开发：

1. **流式**：`ModelClient` 新增 `stream()` 方法，产出 `StreamEvent` 迭代器、终结于一个完整 `AssistantMessage`。**Step 循环不消费流**——协议解析（Block/ToolCall markup）必须拿到完整文本才能跑，流式的唯一消费者是 CLI 的实时渲染。因此 `stream()` 的契约是"边产出增量、最终聚合出与 `complete()` 完全一致的 `AssistantMessage`"，Step 侧零改动或近零改动。
2. **多模态**：`Message.content` 从 `str` 放宽为 `str | list[ContentItem]`（`TextItem | ImageItem`），两个 client 的 request 构造各自翻译；能力矩阵加 `supports_images`。v1 图片入口只有一个：CLI 附件参数（`run --image <path>`）。不做图片生成、不做音视频（ACTION_PLAN 已声明后续增加）。
3. **内嵌指令**：REPL 的裸词命令（`models`/`reload`/`mcp ...`）统一迁移为 `/` 前缀路由（`/model`/`/search`/`/mcp`/`/help`），旧裸词保留一个里程碑的兼容期。`/search` 是唯一有安全面的新指令：走 M10 的 `guarded_urlopen`（SSRF Guard 全套复用），零新依赖。

## 二、借鉴判定（对照 agent）

| agent 侧 | 判定 | 理由 |
|---|---|---|
| `client_claude.py::_parse_stream_response`（遍历 SDK event、`hasattr` 探字段、聚合 usage） | **借鉴思路，不借鉴实现** | 思路对（累积 delta、聚合 usage、最终返回完整消息）；实现用 `hasattr` 链探测 event 形状，脆弱且无类型。ForgeAgent 用显式 `StreamEvent` 联合类型 + 每个 client 自己的 SDK event → StreamEvent 翻译层 |
| `LiveManager`（rich Live 面板渲染流） | **借鉴（简化版）** | CLI 用 `rich.live.Live` 渲染 text delta，但不做 agent 的多面板/语法高亮实时重排——轻量优先 |
| agent 无多模态消息类型 | — | 无可借鉴，按 Anthropic/OpenAI 两家的原生 content-block 形状自行设计 |
| `cli_task.py` 的命令系统（完整 command registry + 补全） | **不借鉴** | 重。ForgeAgent 的 REPL 指令是一个 `dict[str, handler]` 路由就够 |

## 三、架构设计

### 3.1 `StreamEvent` 与 `ModelClient.stream()`（client.py / models.py）

```python
# models.py 新增
class StreamEventKind(StrEnum):
    TEXT_DELTA = "text_delta"          # 正文增量
    THINKING_DELTA = "thinking_delta"  # 思考增量（仅展示，不进对话历史）
    DONE = "done"                      # 终结事件，携带完整 AssistantMessage

class StreamEvent(BaseModel):
    kind: StreamEventKind
    text: str = ""                     # TEXT_DELTA/THINKING_DELTA 的增量文本
    message: AssistantMessage | None = None  # 仅 DONE 事件携带
```

```python
# client.py：ModelClient 新增（带默认实现，非 abstract）
def stream(self, messages, params=None) -> Iterator[StreamEvent | ClientError]:
    """默认实现：complete() 一次拿全量，包装成单个 TEXT_DELTA + DONE。
    子类可覆盖为真流式。ClientError 直接 yield 后终止（与 complete 同语义，不抛异常）。"""
```

关键决策点：

- **`stream()` 有默认实现（degrade-to-complete），不是 abstractmethod**——`MockClient` 与暂未实现真流式的 client 自动可用，全部既有测试零改动；调用方（CLI）对"假流式"与"真流式"无感知。
- **终结事件 `DONE` 携带完整 `AssistantMessage`**——这是唯一进入 Step/对话历史的产物，与 `complete()` 返回值完全同构（含 usage/stop_reason/tool_calls）。**不变量：`stream()` 消费完毕后得到的 AssistantMessage 必须与同请求走 `complete()` 的结果结构一致**（内容一致性受温度影响不做逐字节断言，但字段完整性/usage 语义必须一致），单测按此断言。
- **错误语义与 `complete()` 对齐**：传输错误 yield 一个 `ClientError` 后终止迭代，不抛异常。流中途断线（已产出部分 delta 后失败）同样收敛为 `ClientError`——半截文本不进对话历史，宁可整轮重来，不让被截断的协议标记进解析器。
- **重试边界**：`run_with_retries` 只覆盖"首字节前"的失败（建连/超时/限流）；已开始产出 delta 后的中途失败**不重试**（避免用户看到文本回退重播），直接以 `ClientError` 结束该轮，交给上层反馈环。
- **usage 聚合**：Anthropic 的 usage 分布在 `message_start`（input）与 `message_delta`（output）两处事件，client 内聚合；OpenAI-compatible 需要请求时带 `stream_options: {"include_usage": true}` 才在末帧给 usage，缺失时 usage 全 0（诚实置零，不估算）。

### 3.2 两个 client 的真流式实现

- **AnthropicClient**：SDK `client.messages.create(stream=True)` 返回 event 迭代器；`content_block_delta`(text_delta) → `TEXT_DELTA`，`thinking_delta` → `THINKING_DELTA`，`message_start`/`message_delta` 聚合 usage，`message_stop` 后组装 DONE。
- **OpenAICompatibleClient**：`create(stream=True, stream_options={"include_usage": True})`；`choices[0].delta.content` → `TEXT_DELTA`，`delta.reasoning_content`（GLM/DeepSeek 扩展字段，若存在）→ `THINKING_DELTA`，末帧 usage → DONE。**native tool_calls 的流式增量拼装（arguments 分片到达）v1 不做**——检测到 `delta.tool_calls` 即在该轮内部静默回退为聚合模式（继续收流但不 yield delta，最终 DONE 一次给全量），保证正确性优先。
- 两者均沿用现有 injectable `transport` 模式：新增 `stream_transport` 注入点，测试用假 event 序列驱动，零 key 零网络。

### 3.3 Step/CLI 接线：流式只影响展示层

```
CLI(run/repl, --stream 或配置开关)
  └─ Task(..., on_stream_text=callback)      # 可选回调，None=非流式
       └─ Step: reply = self._stream_or_complete(convo)
            # 有回调 → 消费 client.stream()，TEXT_DELTA 转发给回调，取 DONE.message
            # 无回调 → 原样 client.complete()
```

- Step 内部新增一个私有分支方法，**对既有 `run()` 逻辑的改动仅一行**（`self._client.complete(...)` 换成 `self._stream_or_complete(...)`），后续所有解析/反馈/终止判定完全不变——它们拿到的仍是完整 `AssistantMessage`。
- CLI 侧回调用 `rich.live.Live` + 增量文本渲染；THINKING_DELTA 以 dim 样式区分展示（可配置关闭）。非 TTY（管道/CI）自动降级为非流式。

### 3.4 多模态消息（models.py + 两个 client）

```python
class TextItem(BaseModel):
    type: Literal["text"] = "text"
    text: str

class ImageItem(BaseModel):
    type: Literal["image"] = "image"
    media_type: Literal["image/jpeg", "image/png", "image/gif", "image/webp"]
    data: str          # base64 编码的图片字节

ContentItem = Annotated[TextItem | ImageItem, Field(discriminator="type")]

class Message(BaseModel):
    role: Role
    content: str | list[ContentItem]   # str 形式完全保留，全部既有代码零改动
```

- **`str` 分支保留为主通道**：所有既有构造点（Step 反馈、系统提示）不改；只有携带图片的消息才用 list 形式。
- **client 翻译**：Anthropic → content blocks（`{"type":"image","source":{"type":"base64",...}}`）；OpenAI-compatible → `image_url` 的 data-URI 形式（`data:image/png;base64,...`，两家通吃的最大公约数）。`_split_system`/turn 构造处各加一个 `_render_content()` 翻译函数。
- **能力矩阵**：`ModelCapability.supports_images: bool = False`；`models.yaml` 逐模型标注。不支持图片的模型收到 ImageItem 时，client 返回 `ClientError(kind="invalid_request")`（显式报错，不静默丢图）。
- **图片入口（v1 两个）**：① `forgeagent run "<goal>" --image <path>`（可重复，path 可以是单个图片文件**或目录**——目录时收集其下所有支持格式的图片，非递归，按文件名排序）；② REPL 内嵌指令 `/image <path> [goal...]`（2026-07-12 用户裁决修订：REPL 需要图片入口）——附加图片到下一条 goal，同样支持文件或目录。CLI 读文件→探测 media_type（文件头魔数，stdlib `imghdr` 已废弃，自写 4 分支魔数判断）→ base64 → 拼进首条 user 消息。大小上限 5MB/张（Anthropic API 限制），超限报错；多图总数上限 20 张（Anthropic 单请求限制），超限报错并提示用户筛选。
- **AssistantMessage 不扩展**：目标模型输出仍是文本（无图片生成需求），响应侧零改动。
- **多模态 usage 计数**：延续 M10 裁决 8 的 spike-then-decide——两家 usage payload 里若有稳定的 image/多模态计数字段则映射进 `TokenUsage`，Phase 0 spike 实测后定，无稳定形状就不加字段。
- **reasoning token 计费（2026-07-12 用户补充裁决）**：thinking/reasoning 输出是计费 token，`TokenUsage` 新增 `reasoning_tokens: int = 0`。映射：OpenAI-compatible 从 `usage.completion_tokens_details.reasoning_tokens`（防御性 `getattr` 链，缺失置 0）；Anthropic 的 thinking token 计入 `output_tokens` 本身（API 不单列），spike S1/S2 实测各厂商实际字段名后定稿映射表——已知同义变体：`reasoning`/`reasoning_content`/`reasoningContent`/`thinking`（非流式）与 `delta.reasoning`/`delta.reasoning_content`（流式），client 侧按厂商实测结果做统一归一，不在上层暴露差异。CLI 用量状态行同步显示 `reasoning=N`。

### 3.5 内嵌指令（cli.py）

统一 `/` 前缀路由表，REPL 循环里 `goal.startswith("/")` 一次分发：

| 指令 | 行为 | 依托 |
|---|---|---|
| `/model` | 列出注册模型（复用 `print_models`）；`/model <id或alias>` 切换当前 REPL 会话模型（改 `repl()` 的局部 `model` 变量，client 按次构建所以天然生效；未知 id 报错不切） | 既有 `model_registry` |
| `/search <query>` | 经 `guarded_urlopen` 请求 DuckDuckGo HTML 端点（`html.duckduckgo.com/html/?q=...`），stdlib `html.parser` 提取前 N 条（标题+URL+摘要）打印。**只打印给用户看，不自动注入对话**——用户可复制粘贴进下一条 goal。**Best Effort 定位（用户裁决确认）**：HTML 结构是非契约接口，改版会破坏解析。**错误处理（2026-07-12 用户补充裁决）**：SSRF 拦截 / 非 200 / 解析失败均不向用户抛原始堆栈，捕获后打印友好一行（如"搜索请求被安全策略阻止"/"搜索引擎暂时不可用"），细节进 logger | M10 `ssrf_guard`（SSRF 复检免费获得），零新依赖 |
| `/image <path> [goal...]` | REPL 图片入口（用户裁决修订新增）：path 为图片文件或目录（目录=收集其下全部支持格式图片）。带 goal 则立即随图运行；只给 path 则暂存，附加到下一条 goal | §3.4 的同一套读图/魔数/上限逻辑，CLI 与 REPL 共用 |
| `/mcp` | 等价现有 `mcp status`（显示各 server 状态）+ 追加各 server 的工具清单与"如何使用"一段提示；`/mcp enable|disable <s>` 保留 | 既有 `MCPManager`（工具清单从 `tools_prompt()` 已有数据渲染） |
| `/help` | 打印全部指令一行摘要；`/help <指令>` 打印该指令详细用法 | 路由表自描述（每个 entry 带 usage/description 字符串，help 从表生成，不手写两份） |

- **`/` 即时提示（2026-07-12 用户补充裁决）**：用户输入单独一个 `/`（或 `/` + 未知前缀）时，自动打印全部指令清单（即 `/help` 的一行摘要形态），不让用户猜有哪些指令。不引入 readline 补全（保持零新依赖、轻量），用"敲 `/` 回车即见菜单"达成可发现性。

- **兼容期**：旧裸词 `models`/`reload`/`mcp ...` 本里程碑继续可用（映射到同一 handler），打印一行 deprecation 提示，下个里程碑移除。`reload` 收编为 `/reload`。
- **`/search` 的安全定位**：这是主进程发起的出网，与 WebFetch 同类（T10a 路径）——复用 `guarded_urlopen` 即复用全部 SSRF 防护。**但它是用户亲手键入的指令、非模型发起**，故不过确认门（用户输入本身就是授权）；threat-model 增补一行注明这一区别（见 §四）。
- 指令处理全部在 REPL 层，不进 Task/Step——模型永远看不到这些指令，无提示注入面扩大。

### 3.6 明确不做（v1 范围声明）

- 不做音频/视频输入（ACTION_PLAN 已声明留待后续，→ §九 待实现序列）。
- 不做图片生成/响应侧多模态（→ §九）。
- 不做 native tool_calls 的流式增量拼装（检测到即回退聚合，见 §3.2；→ §九）。
- 不做 `/search` 结果自动注入对话（避免"用户没看过的外部内容直接进模型上下文"这一注入面）。
- 不做 readline 级命令补全/历史（`/` 即时提示已覆盖可发现性；→ §九）。

## 四、threat-model 增量

| # | 威胁场景 | 缓解 |
|---|---|---|
| T11a | `/search` 出网被滥用（构造指向内网的查询 URL） | 查询词经 `urllib.parse.quote` 编码后拼进固定 host 的 URL 模板（host 不可被查询词改写）；请求经 `guarded_urlopen` 全套 SSRF 复检。与 T10a 的区别：用户亲手键入即授权，不过确认门 |
| T11b | 搜索结果/图片文件内容作为外部数据携带提示注入 | `/search` 结果只打印不注入对话（§3.5）；`--image` 是用户自选的本地文件，信任级别同用户输入本身；模型若被图片内嵌指令带偏，生成代码仍被 T1-T3 后端层兜底（延续 T5 分层原则） |
| T11c | 流式中途断线导致半截协议文本进入解析器 | 半截文本不进对话历史，中途失败整轮收敛为 `ClientError`（§3.1 错误语义） |

## 五、开放裁决（8 项，2026-07-12 用户已全部裁决，含修订）

1. `stream()` 采用"默认实现 degrade-to-complete，子类覆盖真流式"的非 abstract 设计（§3.1）？**裁决：同意**。
2. 流式中途失败不重试、不让半截文本进历史，整轮 `ClientError`（§3.1）？**裁决：同意**。
3. OpenAI-compatible 检测到流式 native tool_calls 即回退聚合模式，v1 不做增量拼装（§3.2）？**裁决：同意**（增量拼装列入 §九）。
4. `Message.content: str | list[ContentItem]`，str 主通道保留、仅带图消息用 list（§3.4）？**裁决：同意**——向后兼容的关键。
5. 图片入口（§3.4）？**裁决：修订后同意**——`run --image <path>` 之外，**追加 REPL 内嵌指令 `/image` 入口，且两个入口都需支持多图（path 可为目录，收集其下全部图片）**。已按修订更新 §3.4/§3.5。
6. 内嵌指令统一 `/` 前缀 + 旧裸词一个里程碑兼容期（§3.5）？**裁决：同意**，并**追加**：输入单独 `/` 时自动展示指令清单（可发现性，见 §3.5"`/` 即时提示"）。
7. `/search` 用 DuckDuckGo HTML 端点 + stdlib 解析、结果只打印不注入对话、不过确认门（§3.5/T11a）？**裁决：同意**（"用户亲手键入即授权"的区分获确认），并**追加两点**：① 文档明确标注 Best Effort 定位（HTML 非契约接口）；② 错误处理不得向用户抛原始堆栈——SSRF 拦截/非 200/解析失败均捕获后打印友好一行提示，细节进 logger。已按修订更新 §3.5。
8. golden 任务集扩展？**裁决：同意并加量**——G341-G380（40 个，维持 40/25/20/10/5% 配比，总数 380），覆盖流式降级/多模态拒绝路径/指令路由。

**用户补充裁决（超出原 8 项）**：

- **reasoning token 计费**：thinking/reasoning 输出是计费 token，各厂商字段命名不一（`reasoning`/`reasoning_content`/`reasoningContent`/`thinking`，流式 `delta.reasoning`/`delta.reasoning_content` 等），`TokenUsage` 需纳入这部分计数——落地为 `reasoning_tokens` 字段 + client 侧按 spike 实测归一映射（见 §3.4 修订）。
- **并行开发用 git worktree**：Phase 1/2/4 并行 subagent **必须**各用独立 git worktree（`Agent` 工具 `isolation: "worktree"`），最后合并回主干——根治 M10 的 git add/commit 竟态（从"建议"升级为本里程碑的确定做法）。
- **未实现部分列入待实现序列**：见 §九。

## 六、Phase 0 spike（裁决通过后、编码前）

- S1：Anthropic SDK `stream=True` 的 event 序列真机实测（text_delta/thinking_delta/usage 分布位置），确认 §3.2 的事件映射表；顺带确认 thinking token 在 usage 中的落点（是否并入 output_tokens）。
- S2：OpenAI-compatible 三厂商（gpt-5.4-mini/glm-5.2/deepseek-v4-flash）`stream=True` + `stream_options.include_usage` 实测：**各厂商是否真的支持 `stream_options`（用户特别提示：有厂商可能静默忽略该参数导致末帧无 usage）**、末帧 usage 是否都给、reasoning 字段的实际命名（`reasoning_content`/`reasoning`/其它）、`completion_tokens_details.reasoning_tokens` 有无。实测结果直接决定 §3.4 reasoning_tokens 的映射表。
- S3：两家多模态 request 形状实测（Anthropic content blocks / OpenAI data-URI），各发一张小图确认接受；顺带看 usage payload 有无稳定的图片计数字段（§3.4 spike-then-decide）。
- S4：DuckDuckGo HTML 端点经 `guarded_urlopen` 实测：返回结构、结果条目的 CSS 类名、是否有反爬拦截。
- S5：流式中途断连模拟（假 transport 抛错在第 N 个 event 后），验证 `ClientError` 收敛路径。

## 七、实施 Phase 划分

| Phase | 内容                                                                                         | 文件集                                                                           |
| ----- | ------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------- |
| 0     | 本文档评审 + spike S1-S5                                                                        | docs/                                                                         |
| 1     | `StreamEvent`/`stream()` 默认实现 + 两个 client 真流式 + 单测                                         | models.py, client.py, anthropic_client.py, openai_compatible_client.py, tests |
| 2     | `ContentItem`/`TextItem`/`ImageItem` + client 翻译 + `supports_images` + 单测                  | models.py, 两 client, model_registry/models.yaml, tests                        |
| 3     | Step `_stream_or_complete` + Task `on_stream_text` 透传 + CLI Live 渲染 + `--stream`/`--image` | step.py, task.py, cli.py, tests                                               |
| 4     | `/` 指令路由（/model /search /image /mcp /help /reload + `/` 即时提示）+ 兼容期映射 + 单测                                    | cli.py, tests                                                                 |
| 5     | threat-model T11a-T11c + golden G341-G380 + README                                         | docs/                                                                         |
| 6     | 三次评审 + milestone_009.md 收尾                                                                 | milestones/                                                                   |

Phase 1/2/4 文件集互不重叠可并行；Phase 3 依赖 Phase 1 的 `stream()` 契约，串行其后；Phase 5/6 收尾串行。**并行 subagent 每个使用独立 git worktree（用户裁决，`Agent` 工具 `isolation: "worktree"`），完成后合并回主干**——根治 M10 的 git add/commit 竟态。

## 九、待实现任务序列（本里程碑明确不做，列入后续迭代）

按用户裁决，"目前不做"的项集中登记于此，便于将来版本排期（非承诺清单，做与否届时再裁决）：

| 项 | 来源 | 前置/备注 |
|---|---|---|
| 音频/视频输入（`AudioItem`/`VideoItem`） | §3.6；ACTION_PLAN M10 行已预告 | `ContentItem` 联合类型天然可扩展，加新成员 + client 翻译即可 |
| 图片生成/响应侧多模态（`AssistantMessage` 携带图片） | §3.6 | 需求未证实；出现真实用例再设计 |
| native tool_calls 流式增量拼装（arguments 分片实时解析） | §3.2 裁决 3 | v1 回退聚合已保正确性；只有"流式展示工具调用过程"的 UX 需求出现时才值得做 |
| readline 级命令补全/历史 | §3.6 | `/` 即时提示已覆盖可发现性；补全需引入 readline/prompt_toolkit 依赖,与零新依赖原则冲突，需单独裁决 |
| `/search` 官方 API 引擎（需 key） | §五 裁决 7 | DDG HTML Best Effort 若频繁失效，升级为可配置引擎（Bing/Brave API 等） |
| 执行子进程联网 Broker（代码块内受控出网） | threat-model "未决/明确不做" 延续 | 与 WebFetch 正交；需求驱动，v1 后再评估 |
| M10 遗留：提交 `6ccfcb6` 边界拆分 | milestone_010 遗留问题 | 未 push 前可在整理性提交中处理，优先级低 |
