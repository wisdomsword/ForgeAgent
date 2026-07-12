# 里程碑 M9: 流式支持 + 多模态消息 + 内嵌指令

- 状态: 已完成
- 起止: 2026-07-12 ~ 2026-07-12
- 对应 ACTION_PLAN 行: M9（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_008](milestone_008.md)（M9 曾被用户裁决顺延至 M10 之后补做，见 ACTION_PLAN 顶部说明；本文件记录的是补做的完整过程）

## 目标与范围

摘自 ACTION_PLAN.md §四 M9 行：

- 交付物：**流式支持**（`ModelClient.stream()` + `StreamEvent`）；**多模态消息**（`ContentItem`/`TextItem`/`ImageItem` 联合类型）；内嵌指令包括但不限于 `/model`（列出/切换可用模型）、`/search`（搜索网络资源）、`/mcp`（显示可用 MCP 服务及用法）、`/help`（显示可用命令/详细帮助）；golden 任务集适量扩展。
- 验证：—（未预设具体命令，由本里程碑自定义验收证据）。
- 门禁：视需求排期（弱门禁，不要求用户显式批准）。

设计依据：`docs/m9-streaming-multimodal-commands.md`（8 项裁决 + 用户补充裁决 3 项 + §八 Phase-0 spike 实测 S1-S5 + §四 threat-model 增量 T11a-T11c）。

## 方案设计

8 项裁决（`docs/m9-streaming-multimodal-commands.md` §五，2026-07-12 用户全部裁决，含 2 处修订）：

1. `stream()` 采用"默认实现 degrade-to-complete，子类覆盖真流式"的非 abstract 设计（§3.1）——**同意**。
2. 流式中途失败不重试、不让半截文本进历史，整轮收敛为 `ClientError`（§3.1）——**同意**，这正是本里程碑 Phase 6 代码评审揪出的两个真实 bug 所违反、后又修复落地的核心约束。
3. OpenAI-compatible 检测到流式 native tool_calls 即回退聚合模式，v1 不做增量拼装（§3.2）——**同意**，列入 §九 待实现序列。
4. `Message.content: str | list[ContentItem]`，str 主通道保留、仅带图消息用 list（§3.4）——**同意**，向后兼容的关键。
5. 图片入口（§3.4）——**修订后同意**：`run --image <path>` 之外追加 REPL 内嵌指令 `/image`，两个入口都支持多图（path 为目录时收集其下全部图片）。
6. 内嵌指令统一 `/` 前缀 + 旧裸词一个里程碑兼容期（§3.5）——**同意**，并追加：单独输入 `/` 时自动展示指令清单。
7. `/search` 用 HTML 端点 + stdlib 解析、结果只打印不注入对话、不过确认门（§3.5/T11a）——**同意**（"用户亲手键入即授权"的区分获确认），并追加：①文档标注 Best Effort 定位；②错误处理不得向用户抛原始堆栈。
8. golden 任务集扩展——**同意并加量**：G341-G380（40 个，维持 40/25/20/10/5% 配比，总数扩到 380）。

用户补充裁决（超出原 8 项）：reasoning token 计费需纳入 `TokenUsage`（各厂商字段命名不一，落地为 `reasoning_tokens` + 按 spike 归一映射）；并行开发的 subagent 必须各用独立 git worktree（根治 M10 的 git add/commit 竟态）。

Phase-0 spike（`docs/m9-streaming-multimodal-commands.md` §八，真实 API/网络实测，S5 为模拟 transport）关键发现：

- **S1/S1b**：Anthropic 流式事件序列实测为 `message_start`（usage 占位不可信）→ thinking 块（含遗漏在原映射表里的 `signature_delta`，需静默跳过）→ text 块 → `message_delta`（真实全量 usage + stop_reason）→ `message_stop`。usage 聚合改为以 `message_delta` 为准，而非原设计的"两处分布求和"。thinking token 计入 `output_tokens`，`reasoning_tokens` 对 Anthropic 恒 0。
- **S2**：glm-5.2 的 reasoning token 真值在**非标准顶层** `usage.reasoning_tokens` 字段（标准嵌套位置 `completion_tokens_details.reasoning_tokens` 给的是假零）；gpt-5.4-mini 则相反，真值在标准嵌套位置。映射策略定稿为 `max(嵌套值, 顶层值)`，两处均防御性读取。
- **S3**：两家多模态 request 形状（Anthropic content-block / OpenAI data-URI）实测均正确接受，且均无稳定的图片专属 usage 计数字段——裁决 8 按 spike-then-decide 落地为"`TokenUsage` 不加图片计数字段"。
- **S4（改变设计的发现）**：DuckDuckGo 在本网络环境不可达（连接超时，非反爬），Bing HTML 端点实测可达且结构稳定。`/search` 默认引擎由 DDG 改为 Bing，host 做成可配置常量表，DDG 保留为备选。
- **S5**：模拟 transport 在第 2 个 delta 后抛异常，验证消费循环按 §3.1 语义收敛为单个 `ClientError`、半截文本不进历史——这条路径本身测试充分，但 Phase 6 发现了它未覆盖的姊妹场景（见下）。

对设计的净影响（§八 结论）：①Anthropic usage 聚合改以 `message_delta` 为准；②`reasoning_tokens` 映射定稿为双位置 `max()`；③`TokenUsage` 不加图片计数字段；④`/search` 默认引擎 DDG→Bing。

## 子任务清单

- [x] Phase 0：设计文档 `docs/m9-streaming-multimodal-commands.md` 撰写 + 用户评审（8 项裁决 + 2 处修订 + 3 项补充裁决全部确认）+ Phase-0 spike S1-S5 全部实测（S1-S4 真机，S5 模拟 transport）
- [x] Phase 1：`StreamEvent`/`ModelClient.stream()` 默认实现（degrade-to-complete）+ 两个 client 的真流式覆盖 + 单测
- [x] Phase 2：`ContentItem`/`TextItem`/`ImageItem` 联合类型 + 两 client 的多模态翻译 + `supports_images` capability 字段 + `image_input.py`（路径/目录收集）+ 单测
- [x] Phase 3：`Step` 流式消费 + `Task.on_stream_text` 透传 + CLI `Live` 渲染 + `--stream`/`--image` 参数接线
- [x] Phase 4：`/` 指令路由（`/model` `/search` `/image` `/mcp` `/help` `/reload` + 单独 `/` 即时提示指令清单）+ 旧裸词一个里程碑兼容期映射 + 单测
- [x] Phase 5：threat-model T11a-T11c 增量 + golden G341-G380（40 个，配比精确维持）+ README（`--stream`/`--image` 示例 + 完整 slash 指令清单，替换过时的纯裸词文档）
- [x] Phase 6：对抗性代码评审（委派 `general-purpose` subagent，环境无 `code-reviewer` 类型，同 M6-M8/M10 做法）+ 4 个发现全部修复 + 全量验证 + 本里程碑文件收尾

## 交付物清单

- [x] `src/forgeagent/models.py` — 新增 `StreamEvent`/`StreamEventKind`、`ContentItem`/`TextItem`/`ImageItem` 联合类型、`TokenUsage.reasoning_tokens` 字段
- [x] `src/forgeagent/client.py` — `ModelClient.stream()` 默认实现（非 abstract，degrade-to-complete：调用 `complete()` 后包成单个 TEXT_DELTA + DONE 事件序列）
- [x] `src/forgeagent/anthropic_client.py` — 真流式 `stream()`（SSE 事件消费、thinking/signature_delta 跳过、`message_delta` 权威 usage 聚合）+ 多模态 content-block 翻译；Phase 6 修复：`saw_message_stop` 标志位，生成器无异常静默结束时发 `ClientError` 而非虚构 DONE
- [x] `src/forgeagent/openai_compatible_client.py` — 真流式 `stream()`（chunk 消费、`finish_reason` 权威判定）+ 多模态 data-URI 翻译 + `reasoning_tokens` 双位置 `max()` 映射；Phase 6 修复：同构的 `stop_reason` 空值兜底，未见 `finish_reason` 时发 `ClientError` 而非空 `stop_reason` 的 DONE
- [x] `src/forgeagent/image_input.py` — 新增，图片路径/目录收集 + 编码
- [x] `src/forgeagent/web_search.py` — 新增，Bing HTML 端点 + `guarded_urlopen`（复用 T10a SSRF 复检）+ stdlib 解析，友好错误提示（不抛原始堆栈）
- [x] `src/forgeagent/step.py` — 流式消费分支，半截文本不进历史的收敛逻辑
- [x] `src/forgeagent/task.py` — `on_stream_text` 回调透传
- [x] `src/forgeagent/cli.py` — `--stream`/`--image` 参数；`/` 指令路由完整实现（`_handle_model_command`/`_handle_search_command`/`_handle_image_command`/`_handle_mcp_slash`/`_handle_help_command`/`_print_command_menu`）；旧裸词兼容映射；CLI 用量状态行；Phase 6 修复：`reasoning=N` 补入用量状态行、裸词 "mcp" 词边界修复
- [x] `src/forgeagent/res/models.yaml` — `supports_images` capability 字段补齐
- [x] `tests/test_streaming.py` — 新增，Anthropic/OpenAI-compatible 流式单测（含 Phase 6 新增的 2 个静默截断回归测试）
- [x] `tests/test_multimodal.py` — 新增，多模态消息翻译单测
- [x] `tests/test_web_search.py` — 新增，`/search` 单测（SSRF 拦截路径、query 编码、错误友好提示）
- [x] `tests/test_step.py` / `tests/test_task.py` — 流式接线相关用例扩展
- [x] `tests/test_cli.py` — `/` 指令路由、兼容期裸词、用量状态行单测扩展（Phase 6 新增 `reasoning=N` 用例 + 2 个 mcp 词边界回归测试）
- [x] `docs/m9-streaming-multimodal-commands.md` — 设计文档（8 裁决 + 3 项补充裁决 + Phase-0 spike 实测 S1-S5 + threat-model 增量）
- [x] `docs/threat-model.md` — T11a（`/search` 出网滥用）/T11b（搜索结果/图片提示注入）/T11c（流式中途断线）三行新增
- [x] `docs/golden-tasks-seed.md` — G341-G380（40 个，16/10/8/4/2 精确维持 40/25/20/10/5% 配比），总数扩到 380
- [x] `README.md` — `--stream`/`--image` 示例命令 + 完整 slash 指令清单（`/model`/`/search`/`/image`/`/mcp`/`/reload`/`/help`）+ 旧裸词废弃说明

## 三次评审

### 技术方案评审

- [x] 8 项裁决 + 2 处修订 + 3 项补充裁决逐一对照实现代码确认落地，无方案偏离
- [x] Phase-0 spike 的 4 项净影响（Anthropic usage 聚合改口径、reasoning_tokens 双位置映射、图片计数字段不加、搜索引擎 DDG→Bing）均已体现在最终实现与文档中，不是"先设计后忽略实测"
- [x] §3.6 明确声明"不做"的 5 项（音频/视频输入、图片生成响应、native tool_calls 流式增量拼装、readline 补全、`/search` 官方 API 引擎）均未误做，且已登记入 §九 待实现序列供后续排期

### 代码评审

- [x] 委派 `general-purpose` subagent 对抗性复审 M9 完整 diff（`git diff c2372da..488565a`，环境无 `code-reviewer` 类型，同 M6-M8/M10 做法）
- [x] 发现 4 个问题，全部确认为真实问题并修复：
  1. **high** — `anthropic_client.stream()`：transport 生成器在无异常的情况下静默提前结束（连接中断但 SDK 迭代器直接停止，不抛异常）时，代码从未检测 `message_stop` 事件是否真的出现过，会把已收到的半截文本包装成 `stop_reason` 为空字符串的 DONE 事件误发出去——与 threat-model T11c"中途失败收敛为单个 `ClientError`，半截文本不进入对话历史"的声明矛盾（该声明此前只被 S5 的"显式抛异常"路径验证过，未覆盖"生成器静默耗尽"这个姊妹场景）。修复：增加 `saw_message_stop` 标志位，`while True` 重试循环体内 `for` 事件循环里遇到 `message_stop` 才置真；`try/except` 之后补 `if not saw_message_stop:` 守卫，发 `ClientError(kind="unknown")` 而非虚构 DONE。回归测试：`test_silent_truncation_without_message_stop_yields_client_error_no_done`。
  2. **high** — `openai_compatible_client.stream()` 同构问题：从未检查是否收到过任何带 `finish_reason` 的 chunk，同样会在生成器静默截断时误发 `stop_reason=""` 的 DONE。修复：补等价的 `if not stop_reason:` 守卫。回归测试：`test_silent_truncation_without_finish_reason_yields_client_error_no_done`。
  3. **medium** — `cli.py` 用量状态行缺 `reasoning=N`：`TokenUsage.reasoning_tokens` 已由两个 client 按 spike 实测正确计算，但 `_accumulate_usage`/`_print_usage` 从未消费/展示它，与设计文档 §3.4"CLI 用量状态行同步显示 `reasoning=N`"的用户补充裁决不符。修复：`_accumulate_usage` 补累加、`_print_usage` 补展示字段。回归测试：更新 3 个既有用量断言 + 新增 `test_run_once_prints_nonzero_reasoning_tokens`。
  4. **low/medium** — REPL 兼容层 `goal.startswith("mcp")` 缺词边界：任何以字面子串 "mcp" 开头的正常目标文本（例如"mcpherson's algorithm..."）会被误路由进废弃的裸词兼容分支，当作 `/mcp` 指令处理，而不会作为任务执行——此 bug 早于 M9 存在于潜在写法里，M9 新增的兼容层改动（`d0d72aa`）把它实际落了地。修复：改为显式集合成员判断（bare "mcp"）+ 前缀形式要求带尾随空格（"mcp "）两种情况的判断。回归测试：`test_repl_compat_bare_mcp_word_shows_deprecation`（裸词 "mcp" 仍走废弃兼容路径）+ `test_repl_goal_starting_with_mcp_substring_runs_as_normal_task`（"mcpherson's..." 正常跑任务，不被误路由）。
- [x] 无遗留未处理发现

### 验收评审

- [x] ACTION_PLAN M9 行"验证"列（—，自定义证据）：全量单测 + ruff 证据满足：
  ```
  $ .venv/bin/pytest -q
  444 passed, 11 skipped in 38.91s
  $ .venv/bin/ruff check src tests
  All checks passed!
  ```
  （较修复前的 442 passed 净增 2 个 Phase 6 新增回归测试；11 skip 均为既有 M7/M10 遗留的慢速/环境相关 skip，与本里程碑无关）
- [x] ACTION_PLAN M9 行"门禁"列（视需求排期，弱门禁）：满足。golden 集扩到 380（`grep -oE '\bG[0-9]+\b' docs/golden-tasks-seed.md | sort -u -V | wc -l` = 380），配比核对表 152/95/76/38/19 = 40/25/20/10/5% 精确匹配
- [x] ACTION_PLAN M9 行交付物逐项核对：`ModelClient.stream()`/`StreamEvent` ✓、`ContentItem`/`TextItem`/`ImageItem` ✓、`/model` ✓、`/search` ✓、`/mcp` ✓、`/help` ✓、golden 集扩展 ✓
- [x] 无未满足项

## 遗留问题

- [ ] `/search` 默认引擎 Bing HTML 端点是 Best Effort 依赖（非契约接口，页面结构变化可能导致解析失效）— 影响：搜索功能可能随 Bing 前端改版静默退化 — 计划：暂不处理，已在设计文档 §3.6/README 标注 Best Effort 定位；若频繁失效再按 §九 待实现序列升级为可配置的官方 API 引擎（需 key）
- [ ] native tool_calls 的流式增量拼装未做，检测到即回退聚合模式 — 影响：流式模式下工具调用过程本身不会逐字符展示（只有纯文本回复才有流式体验）— 计划：v1 回退聚合已保证正确性，只有"流式展示工具调用过程"的 UX 需求明确出现时才值得做，已登记入设计文档 §九
- [ ] 音频/视频输入、图片生成/响应侧多模态、readline 级命令补全均未做 — 影响：无，均为设计阶段明确声明的范围外项 — 计划：已登记入设计文档 §九，需求驱动，非承诺清单

## 续接指引

M9 已完成（作为此前被用户裁决顺延、M10 完成后补做的里程碑）：新增 `ModelClient.stream()` 默认实现（非 abstract，degrade-to-complete）+ 两个 client 的真流式覆盖；新增 `ContentItem`/`TextItem`/`ImageItem` 多模态联合类型，`Message.content` 保持 `str | list[ContentItem]` 向后兼容；新增 `/` 前缀内嵌指令路由（`/model`/`/search`/`/image`/`/mcp`/`/help`/`/reload`），旧裸词进入一个里程碑的兼容期（下个里程碑应移除，见 README 废弃说明）；`TokenUsage.reasoning_tokens` 纳入计费追踪并在 CLI 用量状态行完整展示。Phase-0 spike 用真实 API 实测纠正了两处原设计假设（Anthropic usage 权威聚合点、reasoning token 归一映射的真实字段位置），`/search` 引擎因网络可达性问题从 DDG 切换到 Bing。对抗性代码评审发现并修复 4 个真实问题（2 个 high：两个 client 的流式静默截断都会违反 T11c 声明的错误收敛契约；1 个 medium：CLI 用量行漏了 reasoning 字段；1 个 low/medium：REPL 兼容层裸词匹配缺词边界，早于 M9 存在但被 M9 的改动实际触发）。444 单测全绿（较修复前净增 2 个回归测试）+ 11 个既有 skip，ruff 清。golden 集扩到 380，配比精确维持 40/25/20/10/5%。

M9 延续的约束：不硬编码厂商端点/key；流式中途失败必须整轮收敛为 `ClientError`，绝不让半截协议文本进历史——这条约束现在有两条独立路径的回归测试覆盖（显式异常 + 生成器静默耗尽）；三轮评审机制（含对抗性代码评审）在每里程碑收尾执行；`/search` 出网复用 T10a 的 SSRF Guard 全套复检，`/image` 信任级别等同用户输入本身、越权代码仍由 T1-T3 后端层兜底。

下一步：截至本文件收尾，ACTION_PLAN §四里程碑表 M0-M10 均已完成（M9 是本次补做的最后一块拼图）。无显式待启动的下一里程碑；此前会话标记为"待用户确认"的两个废弃 worktree 清理（`agent-a480b4c2133a3fba6`、`agent-a550b897a3be0ca92`）仍未处理，属于破坏性操作，需用户明确同意后再执行。若用户后续有新的里程碑需求（如 §九 待实现序列中的某一项），从该序列中挑选并走标准的"设计文档 → 用户评审裁决 → 编码 → 三轮评审 → 里程碑文件"流程。
