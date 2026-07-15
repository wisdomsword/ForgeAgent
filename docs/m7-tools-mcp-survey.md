# M7 设计草稿：工具插件化 + MCP + Survey + Registry 完善

> **Current runtime addendum (hardening):** This document retains the M7 design record below. MCP servers are now optional by default (`required: false`); an enabled required server that cannot connect aborts CLI startup after cleanup, while an optional failure is sanitized, omitted from the tool catalog, and does not stop the CLI. MCP calls remain main-process trust-boundary calls: `autoApprove` is an explicit per-server/tool exception; otherwise approval requires TTY-capable stdin and stdout, and non-TTY runs reject without reading confirmation input. `--interactive` controls Survey only. The REPL accepts `/mcp ...`, not bare `mcp ...`.

> `MCPManager.close()` now has a single absolute public deadline and one loop-owned drain on the named daemon thread. If cleanup cannot complete, it warns without stack capture or server content/arguments/environment data, retains pending holder/session/loop/thread references, and allows a later close retry rather than claiming success. MCP discovery descriptions mask known sensitive environment values before prompt/CLI use; a discovered tool or configured server name containing such a value is not advertised because a masked alias would not preserve SDK routing. Public status and required-startup diagnostics mask the server identity.

> 状态：**已评审，Phase 0 spike 完成**（2026-07-11 §五 8 项裁决全部确认；`mcp` SDK wire spike + 死亡矩阵 9/9 通过，见 §八）。可进 Phase 1 编码。
> 范围（ACTION_PLAN.md M7 行）：工具集 MCP/Survey 实现；能力登记 YAML + `ModelRegistry`（alias/reload）进一步完善；工具插件化（`ToolRegistry`）；golden 任务集扩到 300 个以内。
> 契约基准：不改 `model-client-contract.md`；扩展 `text-protocol-spec.md`（工具集从 Exec/Edit 扩到 Exec/Edit/MCP/Survey）与 `threat-model.md`（新增 T8：MCP 主进程执行 + 描述注入）。
> 参考来源（只读，判定见 §二）：agent `agent/toolcalls.py::ToolCallProcessor`、`agent/mcp_tool.py::MCPToolManager`、`SurveyToolArgs`/`_call_survey`。

## 一、结论先行

M7 的重心是**把工具从"硬编码两个"变成"可插拔一组"**，然后在这个插件框架上补齐 MCP 与 Survey 两个工具，再顺手完善 Registry 的 alias/reload。四件事有依赖顺序：先做 `ToolRegistry` 地基（纯重构、不改行为、252 测试保持全绿），再挂 Survey（最简单的外部工具，验证插件模式），再挂 MCP（最复杂，引入 `mcp` SDK + 确认门 + 主进程信任边界），最后做 Registry 完善与 golden 扩容。

三个必须在写代码前锁定的前提（用户已裁决，见 §五）：
1. **MCP 只做真实 stdio server**（不做 HTTP/SSE），用官方 `mcp` Python SDK，配置驱动 allowlist，有副作用的调用过人工确认门。
2. **Survey 纳入**，用可注入 asker（不引入 agent 的 promptabs/JSON 表单 DSL）；非交互/headless 环境下转 `task_status=need_info` 终止，不阻塞。
3. **restricted 档下 MCP/Survey 默认可用**——但两者都在**沙箱之外的主进程**执行，所以有副作用的 MCP 调用过确认门，只读调用放行。

一条 M6 教训沿用：**真实 wire 层字段名先核实再写代码**。MCP 这次的 wire 层是 `mcp` SDK 的 `ClientSession`/`stdio_client`/`list_tools()`/`call_tool()` 返回结构——Phase 0 用一个最小 spike 脚本对着**实际安装的 SDK 版本**核实字段名与返回形状，不凭二手文档猜测写入。

## 二、借鉴与不借鉴（对照参考项目逐条判定）

| agent 机制 | 判定 | 理由 |
|---|---|---|
| `ToolCallProcessor.call_tool` 按 `tool_name` enum 分派到 `_call_exec/_edit/_mcp/_survey` | **借鉴思路，重设计形态** | 我们用 `ToolRegistry`（name→`Tool` 实例）替代 if/elif 链，真正做到"加工具=注册一个 Tool"，不改分派代码 |
| `MCPToolArgs(extra='allow')` 全自由参数 | **不借鉴** | 自由 schema 放弃了协议层校验；ForgeAgent 用显式 `MCPArgs{server,tool,arguments}`，`arguments` 才是自由 dict |
| 每个 MCP 工具展开成一个顶层 function 名（`server:tool` 扁平化） | **不借鉴** | 会把工具命名空间撑爆、和文本协议的固定工具名冲突；我们用**单个 `MCP` 工具**，`server`/`tool` 走参数 |
| `MCPToolManager`：trustoken `tt_api_key`、sys/user MCP 双层、磁盘缓存、`_server_status` 状态机 | **大幅精简** | trustoken 全链路不借鉴（CLAUDE.md 已定）；sys/user 双层、跨会话磁盘缓存都是重量级，v1 只要"配置里列出的 server + 启动时 list 一次"即可 |
| `get_tools_prompt()` 把工具 schema 转 Markdown 注入系统提示词 | **借鉴** | 这是让模型知道有哪些 MCP 工具的必要机制；ForgeAgent 同样在任务启动时 discover→拼进系统提示词 |
| `LazyMCPClient`（懒连接、idle_ttl 回收） | **简化借鉴** | v1 用 `mcp` SDK 的 stdio_client 连接，任务级生命周期（任务开始连、结束关），不做 idle_ttl 常驻池 |
| `SurveyRunner.from_json_string` + promptabs JSON 表单 DSL | **不借鉴** | 引入第三方 promptabs 依赖 + 一套表单 schema，与轻量定位冲突；ForgeAgent Survey 用 `prompt`+可选 `options` 的极简内联形态，靠可注入 asker 落地 |
| Survey 引用一个 code block（`args.name` 指向 block）承载表单 JSON | **不借鉴** | 内联 `question` 更直接，省掉"先生成 survey block 再引用"的两步 |
| `processed_ids` 去重、编辑失败跳过后续 Exec | **借鉴（轻量）** | 去重是低成本防错，值得保留；"编辑失败跳过 Exec"当前 ForgeAgent 无此逻辑，按需再定 |

## 三、架构设计

### 3.1 ToolRegistry（地基，Phase 1）

新增 `src/forgeagent/tools.py`：

```python
class ToolContext(BaseModel):
    """一次工具分派可触达的一切。Exec/Edit 用 blocks/backend/runtime/analyzer；
    MCP 用 mcp；Survey 用 asker；确认门用 confirmer。缺席的能力为 None，
    对应工具在 run() 里自检并回结构化错误（而非崩溃）。"""
    # 注：实际以普通 dataclass/attrs 承载不可 pickle 的运行时对象，
    # 这里用伪代码表达字段，非 pydantic 模型。
    blocks: CodeBlockStore
    backend: ExecutorBackend
    runtime: Runtime
    analyzer: CodeAnalyzer
    tier: Tier
    mcp: MCPManager | None = None
    asker: Asker | None = None
    confirmer: Confirmer | None = None


class Tool(ABC):
    name: str                       # 协议里的工具名（"Exec"/"Edit"/"MCP"/"Survey"）
    args_model: type[BaseModel]     # 该工具的参数 schema，喂给解析器做校验
    def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutcome: ...


class ToolRegistry:
    def register(self, tool: Tool) -> None: ...
    def arg_schemas(self) -> dict[str, type[BaseModel]]: ...   # 给 parser
    def get(self, name: str) -> Tool | None: ...              # 给 step 分派
```

- `ExecTool`/`EditTool`：把 `step.py` 现有 `_exec`/`_edit`/`_apply_edit` 逻辑**平移**进来，复用 `CodeBlockStore`（`CodeBlockStore` 从 step.py 移到 tools.py 或独立小模块，避免循环依赖）。
- `MCPTool`/`SurveyTool`：Phase 3/2 新增。
- **默认注册表**：`default_registry(mcp=None, asker=None, confirmer=None)` 返回含 Exec/Edit（+ 视参数注册 MCP/Survey）的 registry。

### 3.2 解析器改造（Phase 1）

`protocol.py` 现在硬编码 `_ARGS_BY_NAME = {"Exec": ExecArgs, "Edit": EditArgs}` 且 `ToolCall.name: Literal["Exec","Edit"]`。改为：

- `parse(text, native_tool_calls=None, tool_schemas=None)`：新增可选 `tool_schemas: dict[str, type[BaseModel]]`，缺省时用 `{"Exec": ExecArgs, "Edit": EditArgs}`（**保持现有 `parse(text)` 调用与全部 protocol 测试不变**）。
- `ToolCall.name: str`（去掉 `Literal`），校验改为"name 不在 `tool_schemas` → 结构化 `ParseError`"（未知工具名仍显式报错、不静默兜底，延续 text-protocol-spec §标记语法）。
- `_build_tool_call` 的 `_ARGS_BY_NAME` 参数化为传入的 `tool_schemas`。`ExecArgs` 的"name/code 至少一个"特判保留（它是 Exec 专属语义，留在 Exec 分支）。

### 3.3 Step 分派改造（Phase 1）

`step.py::_dispatch` 从 isinstance 分支改为 `self._registry.get(call.name).run(call.arguments, self._ctx)`。Step 构造时接收 `registry` 与构建好的 `ToolContext`；`Task` 负责按档位/配置组装 registry 与 context（注入 mcp/asker/confirmer）。

### 3.4 MCP 工具与多 server（Phase 3）

> 设计前提：**Agent 同时接入多个 MCP server 是常态,不是边缘情况**。下面每一条都按"N 个 server 并存"来设计,而非"先支持一个再说"。

**参数 schema**：`MCPArgs{server: str, tool: str, arguments: dict = {}}`。单个 `MCP` 工具名,`server`/`tool` 走参数——多 server 下**天生无命名冲突**:两个 server 都叫 `search` 也靠 `server` 区分,无需 agent 式 `server:tool` 扁平化,也不撑爆工具命名空间。反馈标 `[MCP github:search]`。

**配置 = 事实标准 `mcpServers` 形态**(用户可直接粘贴 Claude Desktop/Cursor 已有配置):
```yaml
mcpServers:
  filesystem:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/data"]
    enabled: true
    autoApprove: [read_file, list_directory]   # 只读,跳过确认门
  github:
    command: docker
    args: ["run","-i","--rm","-e","GITHUB_TOKEN","ghcr.io/github/github-mcp-server"]
    enabled: true
    # 无 autoApprove → 每次调用都过确认门
```
内置 `res/mcp.yaml` 出空 `mcpServers: {}` + 注释示例(不硬编码任何真实 server);用户 `~/.forgeagent/mcp.yaml` 合并(沿用 model_registry 的 built-in+user 合并模式)。`env` 只引用环境变量名,配置里绝不写字面 secret(与 secret_policy 一致)。

**连接模型:一个常驻后台事件循环持有全部 session(多 server 的关键)**
- MCP 首次需要时,`MCPManager` 起一个 daemon 线程跑一个 asyncio loop。
- 启动时对所有 `enabled` server **并发**建连(`asyncio.gather`),每个 server 独立 connect 超时:`stdio_client` → `ClientSession.initialize()` → `list_tools()`,缓存 `server → [tools]`。启动耗时 = max(单 server),非 sum。
- 同步门面:`list_tools()`/`call_tool(server,tool,args)`/`close()` 通过 `run_coroutine_threadsafe(coro, loop).result(timeout=...)` 提交到该 loop 并阻塞取结果——Step 环路保持同步,async 不外溢。
- **为什么不是每次调用 `asyncio.run()`**:stdio server 是有状态的长驻进程,每调用重连会丢 server 端状态 + 每次付握手开销,多 server 下不可接受。正解是一个 loop 持 N 条常驻 session。
- **SDK 生命周期实测点(Phase 0 spike 必做)**:`mcp` SDK 的 `stdio_client`/`ClientSession` 是 async 上下文管理器(`async with ... as session`)。常驻 session 意味着要让这些 `async with` 作用域一直不退出——标准做法是每个 server 跑一个"holder 协程"打开上下文后 await 一个停止事件,调用经队列/共享 session 转发。这套 holder 模式**必须在 Phase 0 对着实际 SDK 版本验证**,不能凭空写(M6 教训)。

**失败隔离是一等公民(多 server 的必然需求)**
- 某 server 建连失败(命令错/崩溃/超时)→ 记为 `unavailable` + 错误原因,其工具不进 catalog,任务用连上的其余 server 继续跑,不整体失败。
- 每次调用有超时:单个 server 挂起不拖垮 loop 或 Step 轮次;超时/失败的调用回结构化错误进反馈环,不影响其他 server。
- 关闭 best-effort、逐 server。

**提示词膨胀控制(多 server 的真实代价)**:N server × M tool 每轮注入 = token 成本 + 上下文压力。按序缓解:① 每 server `enabled` 开关(+ REPL `mcp enable/disable <server>`),只让相关 server 广告工具;② 可选每 server `expose: [toolA, toolB]` 白名单只露子集;③ 提示词按 server 分组、精简 schema(去 `$schema`/`additionalProperties`,借 agent);④ 文档指引"任务只开需要的 server"。

**MCPManager 接口**(新增 `src/forgeagent/mcp_manager.py`):`list_tools() -> [{server, name, description, input_schema}]`(聚合全部 available server)、`tools_prompt() -> str`(按 server 分组的 Markdown,注入系统提示词)、`call_tool(server, tool, arguments) -> MCPResult`、`server_status() -> {server: available/unavailable+reason}`、`enable(server)/disable(server)`、`close()`。

**确认门(多 server 下 per (server,tool) 生效)**：`Confirmer = Callable[[MCPCallRequest], bool]`。`tool in server.autoApprove` → 直接调用;否则 confirmer 返回 True 才调,False 回结构化"用户拒绝"反馈(不是崩溃、不是静默)。CLI 默认终端 y/n;headless/测试注入(默认拒绝)。

**信任边界**：MCP server 全在**主进程**跑(沙箱外),多 server = 更大主进程攻击面;每个 server 是用户显式配置的可信可执行文件,确认门 + autoApprove 按 (server,tool) 兜底。只读调用放行,但其**返回内容**会进反馈环——与"读网页做摘要"同属提示注入面(threat-model T5),MCP 工具**描述**注入系统提示词是新面(T8,见 §四)。

**结果渲染**：MCP 返回的 `content`(文本/结构化)截断后(复用 `_truncate_tail`)+ secret 掩码,渲染成 `[MCP server:tool] ok: ...` 反馈,与 Exec 风格一致。

**v1 不做(记录留位)**：跨会话磁盘缓存工具 schema(agent 2 天 cache)、HTTP/SSE transport、idle-TTL 连接回收池。v1 的"会话级常驻 loop + 并发建连 + 失败隔离"已覆盖真实多 server 需求。

### 3.5 Survey 工具（Phase 2）

- **参数 schema**：`SurveyArgs{question: str, options: list[str] | None = None}`。内联自然语言 `question`（不叫 `prompt`——与"LLM 系统提示词"术语撞车，`question` 语义更准），无 code block 引用，无第三方依赖。**Survey 是"对话"的一部分而非"数据结构"**——问题文本直接连贯地留在响应流里，模型/人/确认门都一眼可读，不必解析引用。
- `options` 可选：给"多选一"类问题用（REPL 里比自由文本更快、更不易错、天然适配确认门菜单 UX）。可选字段，不违背内联对话本质；省略即自由文本问答。
- `Asker = Callable[[SurveyArgs], str | None]`：返回用户答案文本；`None` 表示无交互通道。
- **SurveyTool.run**：`ctx.asker is None or asker(args) is None` → 回一个带 `needs_info` 语义的 ToolOutcome，`Step` 据此把该轮终止为 `Termination.NEEDS_INFO`（detail=question）；否则把答案作为反馈喂下一轮。
- **CLI 装配**：REPL 复用 `read_line` 造 asker；`run` 单次命令默认无 asker（→ need_info）；`--interactive`（可选）允许 run 也交互。测试注入固定答案。
- **Step 侧改动**：新增"工具产出 needs_info"到 `Termination.NEEDS_INFO` 的桥接（当前 needs_info 只来自 front-matter 声明）。

### 3.6 ModelRegistry alias/reload 完善（Phase 4）

现状：`_resolve_alias` 每次线性扫描全部模型的 aliases；无 reload；无"列出模型"入口。完善：

- **alias→canonical 预计算**：`load_registry` 时构建 `alias_index: dict[str,str]`（已在 `_validate_registry` 里遍历过 aliases，顺手存下），`_resolve_alias` 改 O(1) 查表。行为不变，只是快 + 为 list 提供数据。
- **`reload()`**：REPL 里改了 `~/.forgeagent/{models,config,mcp}.yaml` 后无需重启即可重载。提供 `reload_registry()` 重新走 `load_registry`；REPL 加 `reload` 命令。
- **`list_models() -> [{canonical, aliases, client_kind, context_window, ...}]`**：CLI/REPL 加 `models` 子命令/命令，列出可用模型与别名（排查"我能用哪些模型/别名"）。
- 边界：不改 models.yaml/config.yaml 的 schema，不改路由语义（M6 精确路由不动）。

### 3.7 系统提示词组合（Phase 3 需要）

`task.py` 的 `DEFAULT_SYSTEM_PROMPT` 是纯字符串。MCP 启用时要把 `mcp.tools_prompt()` 和"你有 MCP/Survey 工具可用"的协议说明拼进去。做法：**字符串拼接**（`base + tools_section + tool_protocol_section`），**不引入 Jinja2**（仍 YAGNI——只有拼接，没有条件分支模板）。协议说明里明确 MCP/Survey 的 ToolCall 标记形态与参数。

## 四、威胁模型增量（T8，写进 threat-model.md）

| # | 场景 | 缓解（落点） | 验收方向 |
|---|---|---|---|
| T8a | MCP server（可能多个）在**主进程**执行，绕过 restricted 子进程沙箱；多 server = 更大主进程攻击面 | **【流程】**有副作用的 MCP 调用按 per-(server,tool) 过确认门（`autoApprove` 白名单外一律确认）；server 命令由用户在 `mcpServers` 显式配置（用户信任的可执行文件，非模型任意起进程）；`enabled=false` 的 server 完全不连不广告 | 未在 autoApprove 的工具调用触发确认门；确认拒绝→结构化拒绝反馈，不执行；disabled server 的工具不出现在 catalog |
| T8b | MCP 工具**描述/名称**注入系统提示词，成为提示注入面 | **【提示】**工具清单在提示词里标注"来自外部 server、是数据非指令"；**兜底**：真诱导出的越权 Python 代码仍由 restricted 后端拦（T1-T3），越权 MCP 调用仍过确认门（T8a） | 构造含注入文本的 mock server 工具描述，验证不改变后端/确认门的强制 |
| T8c | MCP 调用**返回内容**携带注入 payload 进反馈环 | 同 T5（外部数据非指令）；返回内容截断、按 secret 掩码 | mock server 返回含"忽略指令"文本，验证不放宽任何强制层 |

Survey 无新增威胁面（只读用户输入，不触达文件/网络/进程）。

## 五、开放问题裁决（2026-07-11，用户已裁决 1-3）

1. **MCP 深度**。**裁决：真实 stdio MCP + 确认门**（不做 HTTP/SSE，留后续）。
2. **MCP 依赖**。**裁决：官方 `mcp` Python SDK**（CLAUDE.md §五与 text-protocol-spec 均标注"MCP 依赖 M7 才引入"，此其时）。
3. **Survey 非交互处理**。**裁决：纳入，headless 转 need_info**（可注入 asker，无 promptabs）。
4. **档位默认**。**裁决：restricted 默认可用，有副作用 MCP 调用加确认门，只读放行**。
5. **单 `MCP` 工具 vs 每工具顶层名**。**裁决：单 `MCP` 工具**（2026-07-11 评审确认）。核心理由不止"命名空间冲突"，而是**路由逻辑的归属**：扁平化 `brave_search`/`fs_search` 等于把路由外包给模型（让它记名字，增幻觉）；结构化 `{server,tool}` 把路由**内化为协议**，模型在知情下选择，更稳健。附带三个加分：① 保留完整溯源（评测/调试时知道 `search` 走的哪个 server，不是本地文件还是 Google）；② server 上下线只需更新 catalog、无需改工具名（动态适应性）；③ 与 MCP `ListTools` 的 per-server 返回天然对齐。
6. **Survey 内联 vs 引用 code block**。**裁决：内联 `question`（+可选 `options`）**（2026-07-11 评审确认）。**Survey 是"对话"的一部分，不是"数据结构"的一部分**——问题文本连贯留在响应流里，Parser 无需解析引用（省引用失效/ID 错），REPL/确认门里人一眼可读。参数名用 `question` 不用 `prompt`（避免与"LLM 提示词"术语撞车）。保留可选 `options`（多选一更快、适配确认门菜单，不违背内联本质）。
7. **连接模型**。**裁决：会话级常驻后台 loop + 并发建连 + 每 server 失败隔离**（见 §3.4）。取代草稿的"逐个 `asyncio.run()` 门面"——那对多 server 会丢 server 端状态且串行慢。跨会话磁盘缓存、idle-TTL 池、HTTP/SSE 明确留后续。
8. **建连时机：eager vs lazy**。**裁决：eager**（2026-07-11 评审确认）。**唯一的第一性理由是工具可见性(Tool Discovery for Prompt Injection)**——工具清单必须在系统提示词生成时就绪，模型才知道有哪些工具可调；lazy 建连时提示词无法广告真实工具，模型会**幻觉工具**（编造运行时并不存在的 MCP 工具名）。次要理由：eager 让任务开始前就识别 unavailable server 并从 catalog 剔除，避免任务中途突现连接错误炸掉 Step（正是要避免的 `no_feedback` 类问题）。**关于"确定性 vs 启动延迟"的更正**：ForgeAgent 是通用交互式 agent（不是评测系统，golden 集只是它的验收手段），所以启动延迟是**真实 UX 成本，不能因'是评测'一笔勾销**。延迟的真实抵消是两点：① 并发建连（耗时=max 非 sum）；② REPL 内多任务复用同一 MCPManager，建连成本一次性摊到整个会话。lazy 仅作为"server 成百上千且极少使用"的极端优化保留在架构讨论，不纳入 M7。

## 六、分阶段子任务（规范化，供派发）

> 每个 Phase 收尾都跑 `pytest -q` + `ruff check`，保持全绿再进下一 Phase。编码型子任务按 `subagent-task-template.md` 派发给 subagent（默认 sonnet-5），架构决策留主 Agent。Phase 0 的 spike 与 Phase 6 的三评审由主 Agent 亲自做。

### Phase 0 — 设计评审 + wire spike（主 Agent，门禁：用户批准）
- [ ] 本设计文档过用户评审（尤其开放问题 5/6/8 — **已于 2026-07-11 评审确认，见 §五**）
- [ ] `mcp` SDK wire spike：最小脚本连一个 stdio echo server，核实 `stdio_client`/`ClientSession`/`list_tools()`/`call_tool()` 的真实返回字段与同步/异步形态，记录进本文档"实测更正"节
- [ ] **多 server 关键 spike：验证"常驻 session"holder 模式**——起后台 loop + 一个 holder 协程令 `async with stdio_client(...)/ClientSession(...)` 作用域不退出、`run_coroutine_threadsafe` 从主线程同步调用该常驻 session 成功;再验证**并发连两个 server + 一个故意连不上**时,好的 server 照常可用、坏的记 unavailable 不拖垮
- [ ] **死亡测试矩阵**（常驻 holder 最易在"建连成功之后"出事，逐条验证不挂主进程、不吞异常、其他 server 不受累）：
  - **D1 建连中崩溃**：server 命令存在但 `initialize()` 前退出 → 记 unavailable + 原因，不阻塞其余并发建连
  - **D2 建连超时**：server 启动后迟迟不响应 `initialize()` → 命中 connect 超时、记 unavailable，不无限等
  - **D3 调用中途 server 崩溃**：一次 `call_tool` 打到已死进程（server 在会话中途退出）→ 返回结构化错误进反馈环，不抛未捕获异常炸 Step；该 server 后续标记不可用
  - **D4 调用挂起**：server 收到请求但永不回 → 命中 per-call 超时、结构化超时反馈，**其他 server 的并发调用不受影响**
  - **D5 协议违规**：server 返回非法/畸形 JSON-RPC → 归类为该 server 的错误，不污染其他 server 的 catalog
  - **D6 holder 协程自身异常**：holder 协程因异常退出 → 被后台 loop 捕获、该 server 标 unavailable，**后台 loop 与其余 holder 存活**（一个 holder 死不能连坐整个 loop）
  - **D7 关闭竞态**：`close()` 与 in-flight 调用并发 → best-effort 关闭、in-flight 得到确定的终态（成功或结构化取消），无死锁、无线程泄漏
- [ ] 确认 `mcp` SDK 版本与 `uv add mcp` 可行性（不联网执行下载内容，仅装依赖）

### Phase 1 — ToolRegistry 地基（纯重构，行为不变）
- [ ] `tools.py`：`Tool`/`ToolRegistry`/`ToolContext`，`CodeBlockStore` 迁入或独立
- [ ] `ExecTool`/`EditTool` 平移 step.py 现有逻辑
- [ ] `protocol.py`：`parse(..., tool_schemas=None)`、`ToolCall.name: str`、未知名报错
- [ ] `step.py`：改用 registry 分派，构造 `ToolContext`
- [ ] 验收：252 测试全绿（重构不增删行为）+ 新增 registry 单测（注册/未知名/schema 暴露）

### Phase 2 — Survey 工具
- [ ] `SurveyArgs`/`SurveyTool`/`Asker` 类型
- [ ] Step：工具产出 needs_info → `Termination.NEEDS_INFO` 桥接
- [ ] CLI：REPL asker（复用 read_line）、run 默认无 asker→need_info、测试注入
- [ ] 验收：Survey happy path（有 asker 得答案继续）+ headless（无 asker→need_info）单测

### Phase 3 — MCP 工具 + MCPManager（多 server）
- [ ] `uv add mcp`
- [ ] `mcp_manager.py`：`mcpServers` 配置加载（内置 `res/mcp.yaml` 空槽 + 用户合并、`env` 只引用变量名）、**后台 loop + 并发建连 + 每 server 失败隔离**、`list_tools`（聚合）、`call_tool(server,tool,args)`、`tools_prompt`（按 server 分组 + 精简 schema）、`server_status`、`enable/disable`、`close`、async→sync 门面
- [ ] `MCPArgs{server,tool,arguments}`/`MCPTool`、`Confirmer` 类型 + per-(server,tool) `autoApprove` + CLI 终端确认门实现
- [ ] `task.py`：系统提示词组合（拼 tools_prompt + 协议说明），按配置注入 MCPManager/confirmer；REPL `mcp enable/disable <server>`、`mcp status` 命令
- [ ] `threat-model.md`：新增 T8a/b/c（含多 server 主进程攻击面）
- [ ] 验收：**多 mock stdio server** 端到端（两 server discover 聚合→分组 prompt 注入→按 server 定向 call→反馈）、**单 server 故障隔离**（一个连不上其余照跑）、**按调用超时隔离**（一个挂起不拖垮 Step）、同名工具靠 server 区分不冲突、autoApprove 放行 vs 确认门拦截、确认拒绝→结构化反馈、enable/disable 影响工具可见性

### Phase 4 — ModelRegistry alias/reload 完善
- [ ] alias→canonical 预计算索引；`_resolve_alias` 查表
- [ ] `reload_registry()` + REPL `reload` 命令
- [ ] `list_models()` + CLI/REPL `models` 命令
- [ ] 验收：alias O(1) 解析回归、reload 生效、list 输出正确单测

### Phase 5 — golden 扩到 300 + 文档同步
- [ ] `golden-tasks-seed.md` 增 G201–G300（新增 MCP 工具类 + Survey 类，维持 40/25/20/10/5 配比），文末配比核对表更新到 300
- [ ] `text-protocol-spec.md`：工具集 Exec/Edit → +MCP/Survey，标记语法与参数 schema 补齐，差异表更新
- [ ] `README.md`：MCP 配置说明、Survey 行为、`models`/`reload` 命令、档位与确认门说明
- [ ] `ACTION_PLAN.md`：M7 状态摘要更新

### Phase 6 — 三评审 + 里程碑收尾（主 Agent）
- [ ] 技术方案评审：对照本文档裁决核对无偏离
- [ ] 代码评审：委派 subagent 对抗性复审本里程碑 diff（同 M6 因环境无 code-reviewer 类型，用 general-purpose 替代）
- [ ] 验收评审：`pytest -q`/`ruff check` 原样贴输出；真实 MCP 冒烟——**同时接两个真实 stdio server**（如 filesystem + 另一个官方示例 server）作为最强证据，验证多 server discover 聚合、按 server 定向调用、确认门在真实 server 上生效
- [ ] 产出 `milestones/milestone_007.md` + 更新 `milestones/latest`

## 七、单测清单（比照 text-protocol-spec / m6 的可测性要求）

- **Registry**：注册工具后 `arg_schemas()` 含其名；`get(未知名)` 返回 None；`parse` 用扩展 schemas 认得 MCP/Survey 标记，未知名仍报 `ParseError`。
- **ExecTool/EditTool**：平移后行为与旧 step 用例逐一等价（复用现有 test_step 断言）。
- **SurveyTool**：有 asker→答案进反馈；无 asker→need_info 终止（detail=question）；`options` 透传给 asker；`question` 字段名（非 `prompt`）。
- **MCPManager（多 server）**：`mcpServers` 配置合并（内置空槽 + 用户）；**两 server 并存**下 list_tools 聚合、tools_prompt 按 server 分组；`call_tool(server,tool,args)` 按 server 定向；**同名工具**在两 server 下靠 server 参数区分、各自命中正确 server；**单 server 启动失败**降级为 unavailable、其余 server 照常可用、任务不崩溃；**按调用超时**隔离（一个 server 挂起返回结构化超时、不拖垮其他调用）；`enable/disable` 影响 catalog 与 tools_prompt；async→sync 门面正确、`close()` 逐 server best-effort。
- **MCPTool 确认门（per server,tool）**：`autoApprove` 内放行、外过门；confirmer False→结构化拒绝、不调用 server；不同 server 各自的 autoApprove 互不影响。
- **提示注入回归**：mock server 工具描述/返回含注入文本，断言确认门与后端强制不放宽。
- **ModelRegistry**：alias O(1) 解析等价旧行为、reload 反映文件变更、list_models 字段正确。

---

**评审状态（2026-07-11）**：§五全部 8 项裁决已确认——1-4（MCP 深度/依赖/Survey headless/档位默认）、5（单 MCP 工具）、6（Survey 内联 `question`+`options`）、7（多 server 常驻 loop + 并发建连 + 失败隔离）、8（eager 建连）。无待拍板项。Phase 0 spike 已完成（§八），可进 Phase 1。

## 八、Phase 0 spike 实测结论（2026-07-11，`mcp==1.28.1`）

spike 代码在 `scratch/m7_mcp_spike/`（echo_server.py + spike.py，throwaway 不进包）。对着**实际安装的 SDK** 验证，**9/9 通过**。以下是写 MCPManager 前必须锁定的 wire 层事实：

**SDK API 形态（供 MCPManager 直接照抄）**
- `stdio_client(StdioServerParameters(command, args, env, cwd, encoding, encoding_error_handler))` → async CM，yield `(read, write)` 两条流。`env` 是 dict（`str→str`），配置里只放变量名、装配时从 `os.environ` 取值（沿用 secret_policy）。
- `ClientSession(read, write)` → async CM；`.initialize() -> InitializeResult`、`.list_tools() -> ListToolsResult`（`.tools[i].name/.description/.inputSchema`）、`.call_tool(name, arguments: dict, read_timeout_seconds: timedelta) -> CallToolResult`。
- **`call_tool` 自带 `read_timeout_seconds`（`datetime.timedelta`）——per-call 超时是 SDK 原生能力，不用自己在门面里加 wait_for**。实测超时抛 `McpError: Timed out while waiting for response`，正好命中 D4。
- `CallToolResult.content` 是 list，文本项 `c.type == "text"` 时取 `c.text`（渲染反馈时按此过滤 + `_truncate_tail` + secret 掩码）。

**holder 模式成立（§3.4 的核心假设已验证）**
- 每 server 一个 holder 协程：`async with stdio_client(...) as (r,w): async with ClientSession(r,w) as s: await s.initialize(); publish(s); await stop_event`——`await stop_event` 令两层 `async with` 作用域常驻，session 跨多次同步调用存活。实测同一 held session 连续两次 `echo` 均成功。
- 同步门面 `run_coroutine_threadsafe(coro, loop).result(timeout)` 从主线程调用后台 loop 上的常驻 session，成功。Step 环路可保持同步。
- **外层 `.result(timeout)` 必须 > 内层 `read_timeout_seconds`**，否则门面超时先于 SDK 超时触发、拿不到结构化的 `McpError`。实测 outer=inner+3 时 SDK 超时正确先行。

**死亡矩阵实测（holder 的隔离性）**
- **D1 建连失败隔离** ✅：`command` 指向不存在的可执行文件 → holder 捕获 `FileNotFoundError`、记 `unavailable`，**并发建连的其余 server 照常 available**。
- **D3 调用中途 server 崩溃** ✅：server 在 tool 里 `os._exit(7)` → `call_tool` 抛 `McpError: Connection closed`，门面转结构化错误进反馈、不抛未捕获异常炸 Step。
- **D4 调用挂起 + 其他 server 不受累** ✅：一个 server `sleep(999)` → 该调用命中 2.0s SDK 超时返回结构化错误，**同一 manager 下另一 server 的调用正常返回**。
- **同名工具靠 server 路由** ✅：两个 server 都暴露 `echo`，`{server,tool}` 定向调用各自命中正确 server（坐实开放问题 5 的单 MCP 工具设计）。
- D2（建连超时）/D5（协议违规）/D6（holder 协程自身异常）/D7（关闭竞态）的机制已在 holder 的 `except BaseException` + `connect_all` 的 `wait_for` + `close` 的 stop-event 中覆盖；Phase 3 落 MCPManager 时补成正式单测（spike 已验证同构的 D1/D3/D4 路径）。

**对 MCPManager 实现的直接约束**
1. 门面对每个调用用 `outer_timeout = call_timeout + 余量`，`read_timeout_seconds=timedelta(seconds=call_timeout)`，两者不可混用同一值。
2. holder 的 `except` 必须是 `BaseException`（asyncio 的 `CancelledError` 不是 `Exception`），否则取消/关闭时 holder 会漏异常、连坐 loop。
3. `connect_all` 用 per-server `wait_for(ready, connect_timeout)`，某 server 卡在 `initialize()` 不拖垮其他 server 的就绪等待。
4. 关闭走 stop-event（`loop.call_soon_threadsafe(loop.stop)` 收尾），不要直接 `loop.close()` 抢占 in-flight。

## 九、Phase 6 三评审记录（2026-07-11）

**技术方案评审（主 Agent）**：8 项裁决逐一对照实现代码确认落地（D1-D2 stdio+官方 SDK、D3 Survey headless→need_info、D4 确认门 `if not auto_approved: if confirmer is None or not confirmer(): refuse`、D5 单 MCP 工具 `{server,tool}`、D6 Survey 内联、D7 常驻 loop+holder+隔离、D8 eager 建连+tools_prompt 注入）。无方案偏离。

**代码评审（委派 general-purpose subagent 对抗性复审，因环境无 code-reviewer 类型）**：确认门无绕过路径、解析器泛化无回归、Survey needs_info 桥接（声明完成优先）、超时数学、`_resolve_env` 不泄值——均判定 clean。发现 **5 个真实 bug（非 nit）+ 1 条线程安全说明**，已全部修复并加回归测试：

- [x] **#1（子进程泄漏，close）**：`close()` 原把 `stop.set()` 与 `loop.stop()` 排进同一批 `call_soon_threadsafe`，holder 从 `await stop.wait()` 恢复前 `run_forever` 已 break，两层 `async with __aexit__`（终止子进程）从不执行 → 每次 open/close 泄漏子进程。修复：`close()` 提交一个协程到 loop 内 `stop.set()` 全部 holder + `gather` 等它们跑完 `__aexit__`，**再** `loop.stop()`。回归测试 `test_close_terminates_child_processes_no_leak` 断言 close 后 `pgrep` 存活子进程归零。
- [x] **#2（enable 空操作）**：`enable()` 原只翻 `config.enabled` 标志，`connect()` 有 `if self._started: return` 且无 per-server 重连路径 → 启动时 disabled 的 server 一辈子上不了线。修复：抽 `_start_holders(names)`，`enable()` 在 loop 已起时为该 server 启动 holder。回归 `test_enable_startup_disabled_server_connects_it`。
- [x] **#3（MCP 结果未 secret 掩码，偏离 §3.4）**：executor 输出走 `mask_secrets`，MCP 内容没走。修复：`MCPManager` 构造期抓 `sensitive_env_values()`，`call_tool` 的成功文本与错误文本都过 `mask_secrets`。回归 `test_mcp_result_secret_values_are_masked`。
- [x] **#4（env 继承不一致，偏离 §八）**：`cfg.env` 为空时传 `None`（SDK 用 stripped 默认 env），非空时传全量 `os.environ` → 加一个无关变量会静默翻转继承面，且空 env 的 server 缺 PATH/NODE_PATH 起不来。修复：统一 `env={**os.environ, **_resolve_env(cfg.env)}`。
- [x] **#5（崩溃 server 仍标 available，偏离 D3）**：mid-call 崩溃时 holder 仍 park 在 `stop.wait()`、`except` 不触发，死 session 从不 pop。修复：`call_tool` 的 `except` 里主动 `pop(server)` + 标 unavailable，掉出 catalog。回归 `test_mid_call_crash_marks_server_unavailable`。
- [x] **#6（跨线程无锁，说明非 bug）**：`_states`/`_sessions`/`_holders` 被 loop 线程与调用线程读写，CPython GIL 下单 dict/attr 操作原子、唯一 TOCTOU 有 `session is None` 兜底。加类 docstring 说明，若将来跑 free-threaded 解释器再加锁。

**附带补齐（评审指出的 Phase-3 清单缺项）**：REPL `mcp enable/disable <server>` 命令（原只有 `mcp status`）——依托修复后可用的 `enable()`/`disable()` 实现，`_handle_mcp_command` 承载，测试 `test_handle_mcp_command_status_enable_disable`。

**验收评审**：`pytest` 298 passed / 1 skipped（跳过的是慢速 hung-call，等价路径已在 Phase-0 spike D4 验证）、`ruff` clean。修复后新增 8 个测试（5 个 MCP 回归 + 2 个 CLI mcp 命令 + 1 个 secret 掩码），全部覆盖上述发现。
