# CodeGraph CLI 与 MCP 对照验证设计

> 版本：R1（评审修订版，回应 P0×4 / P1×4 / P2×2）
> R1 相对初版只做一件事：把初版中"未定义"或"自相矛盾"的规格钉死为可执行判据。
> 目标、固定案例、三层 token 口径均不变。

## 目标

用一个固定、可重复的小案例，验证 CodeGraph CLI 与 `codegraph_explore` MCP 在以下方面的差异：

1. 输出细节是否一致，以及差异出现在哪一层；
2. symbols、files、source 行数、调用次数等计数的定义是否被混用；
3. 结果正文、传输包装和模型可见上下文各自消耗多少近似 token。

本验证不调用 LLM，不测 provider 账单，不修改 ForgeAgent 运行时，也不新增依赖。

## 固定案例

查询固定为：

```text
Runtime set_state
```

固定项目路径为：

```text
/Users/admin/Code/llm-agent/ForgeAgent
```

两条路径均使用 `max-files=1`，并读取同一份已经建立的 CodeGraph 索引；共享 daemon 是否可用单独记录，fallback 时仍要求索引指纹一致。CLI 必须使用 `--no-color`，避免 ANSI 转义序列影响比较。

CLI 命令：

```bash
codegraph --no-color explore \
  --path /Users/admin/Code/llm-agent/ForgeAgent \
  --max-files 1 'Runtime set_state'
```

MCP 参数：

```text
codegraph_explore({
  projectPath: "/Users/admin/Code/llm-agent/ForgeAgent",
  maxFiles: 1,
  query: "Runtime set_state"
})
```

（参数名 `projectPath` / `maxFiles` 已与 server 实际 tool schema 核对一致。）

实验只保存 stdout、MCP 原始 `CallToolResult` 和解析后的文本，不保存环境变量或密钥。

### R1 新增：MCP 调用路径（初版未定义，阻塞项）

**执行主体固定为：Python 脚本经 MCP stdio 协议直连 codegraph server。**

| 项 | 取值 |
|---|---|
| 解释器 | `.venv/bin/python`（仓库内既有虚拟环境） |
| SDK | `.venv` 既有 `mcp` 1.28.1；**不写入 `pyproject.toml`，不算新增依赖** |
| 连接方式 | `StdioServerParameters(command="codegraph", args=["serve", "--mcp", "--path", PATH, "--no-watch"])` |
| 配置来源 | 实际使用的 `StdioServerParameters`；`~/.claude.json` 仅记录为环境 provenance（type `stdio`） |
| 会话模型 | **单个 session 复用以完成全部 10 次调用** |

会话模型这一条是刻意选择：MCP 的 `initialize` / `tools/list` 握手是**每次连接一次**，不是每次调用一次。复用 session 更贴近真实 agent 的调用形态；握手和 JSON-RPC framing 不计入本设计的 payload 指标。若 session 中途断开，记录断点并整组重跑。

**明确排除的两条路径**（初版未排除，会导致按本设计无法产出结果）：

- **经 ForgeAgent `mcp_manager`**：`src/forgeagent/res/mcp.yaml` 为 `mcpServers: {}`，`~/.forgeagent/mcp.yaml` 只注册了 filesystem 与 github，无 codegraph。要使用它必须先改运行时配置，直接违反"不修改 ForgeAgent 运行时"。
- **经 `claude --print` 间接调用**：拿不到原始 `CallToolResult`，`CallToolResult JSON` 与 `T_wire_payload` 两列按定义无法产出。

## 输出层次与判定

### 逻辑正文

- CLI 的逻辑正文是完整 stdout。
- MCP 的逻辑正文是 `CallToolResult.content` 中所有 `type == "text"` 项按数组顺序拼接的文本（R1 钉死顺序与过滤条件）。
- 首先做原始字符串和 UTF-8 bytes 精确比较。
- 然后只移除 CLI 末尾**恰好一个**换行（等价于 `removesuffix("\n")`），再次比较。不得使用 `strip()` 或 `rstrip()`，因为它们会隐藏正文边界上的空格差异。

原始比较失败不等于 CodeGraph 内容不同；必须同时报告失败位置和归一化比较结果。

### 传输包装

分别记录：

- CLI stdout 的 UTF-8 字节数；
- MCP `content[].text` 拼接结果的 UTF-8 字节数；
- MCP `content[]` 数组 JSON 序列化后的 UTF-8 字节数（**R1 新增**，用于分离转义开销）；
- MCP `CallToolResult` 对象 JSON 序列化后的 UTF-8 字节数（不含 JSON-RPC framing）；
- CLI/MCP 的 stderr 或诊断日志不计入上述正文和 wire 数字。

**R1 钉死序列化参数**（初版未定义，同一对象可差 37 bytes）：

| 参数 | 取值 |
|---|---|
| 完整对象 | `json.dumps(result.model_dump(mode="json", by_alias=True, exclude_none=False), ensure_ascii=False).encode("utf-8")` |
| content 数组 | `json.dumps(result.model_dump(mode="json", by_alias=True, exclude_none=False)["content"], ensure_ascii=False).encode("utf-8")` |
| 字段过滤 | 两种序列化都不排除 None 字段（`meta` / `structuredContent` / item metadata 为 None 时仍计入） |
| 对照值 | 同时记录 `ensure_ascii=True` 的字节数，作为编码敏感性对照 |

CLI 是进程 stdout，MCP 是结构化 tool result；两者的 payload 数字不能直接解释为"源代码内容大小"。

### R1 新增：wire 增量归因（防止结论被误读）

MCP 对象 JSON 与 CLI stdout 的差不是单一原因，必须分解为四项后再报告：

1. **字符串转义**：`json.dumps(MCP text, ensure_ascii=False)` − MCP text。
2. **content 数组结构**：`content[] JSON` − JSON 字符串值。
3. **结果对象字段**：`CallToolResult JSON` − `content[] JSON`。
4. **CLI 尾部换行**：CLI stdout 比其规范化正文多 1 字节。

总差值按 `字符串转义 + 数组结构 + 对象字段 - CLI 尾部换行` 计算。不把对象 JSON 增量解释为"MCP 协议更重"；本设计没有采集完整 JSON-RPC 帧。实测该案例下增量主要来自第 1 项（对含大量换行与制表符的代码文本做 JSON 转义），数组结构和结果字段分别单列。

### 报告字段

从共同正文中分别提取以下字段，不做跨字段求和。R1 为每个字段钉死可执行的匹配式：

| 字段 | 提取方式 |
|---|---|
| `reported_symbols` | `Found (?P<N>\d+) symbols?` |
| `reported_files` | `across (?P<F>\d+) files?` |
| `source_line_count` | 代码围栏（` ``` `）内匹配 `^\d+\t` 的行数 |
| `blast_radius_entry_count` | 从 `^\*\*Blast radius` 到下一个 `^\*\*` 标题之间，`^- ` 开头的行数 |
| `not_shown_entry_count` | 从 `^\*\*Not shown above` 到文末，`^- ` 开头的行数 |

两处复数形式必须写 `?`：实测输出为 `Found 8 symbols across 1 file.`，`--max-files 1` 时 `files` 是单数 `file`，初版定死的 `across F files` 在该案例下**匹配失败**。

示例中当前一次基线报告为 `8 symbols across 1 file`；这个值用于检查输出稳定性，不写死为产品契约。

**R1 移除：`invocation_count` 不再是报告字段。** 初版把它列在"从共同正文中提取"的字段里，但调用次数不在正文中、无法提取，它是实验自身的执行次数。该字段在结果表中恒等于重复次数，作为观测量信息量为零。R1 将其移入实验元信息（固定值，两条路径相同）。

## Token 口径

使用仓库已有的 `forgeagent.context` 估算函数：

- `estimate_text_tokens(text)`：结果文本近似 token 数；
- `estimate_request_tokens(messages, config)`：带消息和请求 framing 的近似 token 数。

记录三列：

1. `T_result_raw`：对各自原始逻辑正文估算；CLI 包含其 stdout 尾部换行，MCP 使用 `content[].text` 拼接结果；
2. `T_result_normalized`：对移除 CLI **恰好一个**协议尾部换行后的正文估算，用于跨路径内容对照；
3. `T_wire_payload`：对 CLI stdout 或 MCP `CallToolResult` 对象 JSON 估算，表示 payload 表示；不包含 JSON-RPC framing；
4. `T_context`：把固定前缀和对应结果拼入固定结构的 `Message` 请求后估算，表示模型可见上下文的受控代理。

### R1 重大修订：`T_context` 主口径改为 text-only

初版把 MCP 的 JSON 信封塞进 `T_context`，与 `T_wire_payload` 使用同一份输入。这造成两个问题：

1. `T_context` 与 `T_wire` 高度重复，第三层失去独立意义（实测两者 delta 分别为 +143 与 +140，几乎相同）；
2. **本设计的模型可见代理不应假定宿主会把 JSON 信封原样展示给模型**。常见宿主会把 `CallToolResult.content[].text` 投影进上下文，但具体宿主的序列化方式仍是实现细节。

因此 R1 规定：

- **`T_context` 主口径 = text-only**：两侧仅命令/工具标识与参数表示不同，结果部分都用逻辑正文。这测的是"调用方式本身的表达成本"。
- **对象 JSON 口径作为对照列**保留，并明确标注"与 `T_wire_payload` 输入重叠，仅作对照，不作为模型可见上下文的结论"。

### R1 钉死的 `T_context` 构造

以下字面量与结构必须原样使用，否则结果不可复现：

| 项 | 取值 |
|---|---|
| 消息条数 | **固定 2 条**：`[system, user]` |
| system 内容（字面量） | `You are a coding assistant. Use the provided tool output to answer the user's question.` |
| `ContextConfig` | `ContextConfig()` 默认值；本实验 content 全为 `str`，config 不参与估算（仅 content 为 list 且含非 TextItem 时才用到 `image_token_reserve`） |
| CLI user 模板 | `Command: codegraph --no-color explore --path {path} --max-files {max_files} '{query}'` + `\n\nResult:\n` + CLI stdout 去掉恰好一个末尾换行 |
| MCP user 模板 | `Tool: codegraph_explore({"projectPath": "{path}", "maxFiles": {max_files}, "query": "{query}"})` + `\n\nResult:\n` + MCP 正文 |

消息条数必须固定：`estimate_message_tokens` 每条消息加 4、请求整体加 2，条数变化会直接污染 delta。

`T_context` 报告中同时给出包装增量：`delta = MCP - CLI`。

### 近似口径声明

这些数字是仓库定义的保守近似，不是特定 provider 的 BPE 账单。因为基础实验没有模型请求，`TokenUsage.input_tokens`、`output_tokens` 和 provider 费用统一记为 `N/A`。若未来增加真实模型回放，provider usage 作为独立列，不替代前三列。

## 重复运行与稳定性

**R1 钉死执行顺序：交替执行 `(CLI, MCP)` × 10，共 20 次调用。**

初版只说"各执行 10 次"，未定义顺序。分批（先 10 次 CLI 再 10 次 MCP）与交替（成对执行）在存在单调漂移时结论不同——分批会把时间漂移误判为 CLI 与 MCP 的差异。`codegraph explore` 输出自述 "re-read from disk on this call"，磁盘内容变化会直接改变输出，因此交替是唯一可辩护的选择。

### R1 新增：索引状态判据（初版"确认索引状态没有变化"无可执行定义）

指纹取 `codegraph --no-color status -j <path>` 的以下字段：

```text
(lastIndexed, fileCount, nodeCount, edgeCount, pendingChanges)
```

- **排除 `dbSizeBytes` 与 `walSizeBytes`**：它们是物理尺寸，与索引语义无关，可能因查询活动变化而产生假阳性。
- `pendingChanges`（`added` / `modified` / `removed`）是 codegraph 原生提供的"索引是否有待同步变更"信号，为首选判据。
- 频度：每对调用前 1 次，整组结束后 1 次，共 11 次。
- 判定：任一指纹与首帧不一致 → 整组结果标记为不可比，重新开始。

### R1 新增：自污染防护（初版未考虑）

`codegraph` 会索引仓库内文件。若脚本或每轮产物写入被索引的仓库目录，实验自身会改变后续调用的输入。

- 脚本与 10 对原始产物**必须写入仓库外目录**（如 `/tmp/codegraph-parity-<timestamp>/`）；
- 汇总报告在 20 次调用全部结束之后才可入库——入库动作发生在测量窗口之外，不影响结果。

### 稳定性判据

对正文和报告字段做确定性检查：

- 10 次归一化正文必须完全一致；
- `reported_symbols`、`reported_files`、各类条目数必须稳定；
- 若仅 CLI 末尾换行不同，记录为 transport formatting 差异；
- 若归一化正文不同，停止汇总并检查索引同步、daemon 状态和查询参数。

不把进程启动时间、daemon 延迟或终端渲染时间纳入本案例结论；它们属于另一个性能实验。

## 结果表

最终报告使用以下固定列：

| 指标 | CLI | MCP | 口径 |
|---|---:|---:|---|
| 调用次数 | 10 | 10 | 实验参数（常量，非观测量） |
| 报告 symbols | 实测 | 实测 | 报告头字段 |
| 报告 files | 实测 | 实测 | 报告头字段 |
| source 行数 | 实测 | 实测 | 带行号代码行 |
| Blast radius 条目 | 实测 | 实测 | 独立计数 |
| Not shown 条目 | 实测 | 实测 | 独立计数 |
| 正文 UTF-8 bytes | 实测 | 实测 | CLI stdout / MCP text |
| `content[]` JSON bytes | — | 实测 | 含 JSON 转义与数组结构 |
| `CallToolResult` JSON bytes | stdout | 对象 JSON | 不含 JSON-RPC framing |
| JSON 增量归因 | — | 实测 | 字符串转义 / 数组结构 / 对象字段 / CLI 尾换行 |
| `T_result_raw` | 估算 | 估算 | 原始正文 |
| `T_result_normalized` | 估算 | 估算 | 规范化正文 |
| `T_wire_payload` | 估算 | 估算 | payload 表示 |
| `T_context`（text-only，主口径） | 估算 | 估算 | 模型可见代理 |
| `T_context`（对象 JSON，对照） | 估算 | 估算 | 与 `T_wire_payload` 输入重叠 |
| provider `TokenUsage` | N/A | N/A | 本实验无 LLM 请求 |

## 环境指纹

**R1 新增章节。** 本案例的输出格式与索引内容都依赖环境，以下项必须与结果一同记录，否则结果无法被他人复现或比对：

| 项 | 获取方式 |
|---|---|
| codegraph 版本 | `codegraph --version` |
| 索引构建版本 | `status -j` → `index.builtWithVersion` / `currentExtractionVersion` |
| 是否建议重建索引 | `status -j` → `index.reindexRecommended` |
| 索引时间 | `status -j` → `lastIndexed` |
| daemon | `codegraph daemon` 输出；若不可用则记录 shared-daemon / in-process fallback |
| MCP server 配置 | 实际使用的 `command` / `args` 及其来源文件 |

实测该仓库当前为：codegraph 1.6.0，索引由 1.0.1 构建（extraction v24，当前 v25），`reindexRecommended: true`。**索引相对二进制是陈旧的。** 这不影响 CLI 与 MCP 的对照结论（两条路径读同一份索引），但采样前必须记录，否则重建索引后得到的不同数字将无法归因。

## 已知基线与限制

**R1 新增：已核验探针基线。** 以下为单次探针实测值（非 10 次中位数），用于校验实验装置是否搭对；正式结论以 10 次运行的 min/max/median 为准。

| 项 | 实测 |
|---|---|
| CLI stdout | 5030 bytes / 5007 chars，末尾 1 个 `\n` |
| MCP text | 5029 bytes / 5006 chars，无末尾换行 |
| 精确比较 / 归一化比较 | False / **True** |
| MCP `content[]` JSON | 5284 bytes（编码与结构 +255） |
| MCP `CallToolResult` 对象 JSON（ensure_ascii=False） | 5357 bytes（对象字段 +73）；`ensure_ascii=True` 时 5394 bytes |
| CallToolResult JSON − CLI stdout | +327 bytes（规范化正文基准为 +328；CLI 尾换行再减 1） |
| `T_result_raw` | CLI 1421 / MCP 1420 |
| `T_result_normalized` | 1420（两侧共享） |
| `T_wire_payload` | CLI 1421 / MCP 1561 |
| `T_context` text-only | CLI 1491 / MCP 1496（delta **+5**） |
| `T_context` 对象 JSON | CLI 1607 / MCP 1635（delta +28） |

注意 text-only 与对象 JSON 是两个不同问题：+5 是"调用方式的表达成本"，对象 JSON 对照值还包含 payload 编码开销，不应解释为模型实际账单。

当前一次实测显示：CLI 与 MCP 的逻辑正文在移除 CLI 结尾换行后相同；CLI stdout 多一个换行；MCP 完整 JSON 比 MCP text 多协议包装字段。该观察用于验证实验设计，不保证所有查询、索引版本或 CodeGraph 版本都相同。

本设计不比较不同模型 tokenizer，不评估 CodeGraph 查询正确性，不衡量 CLI/MCP 延迟，也不把结构化协议包装误称为源代码细节。

## 验收标准

验证完成必须能回答：

1. 两条路径的正文是否精确相同，若不相同，首个差异是什么；
2. 哪些数字是 CodeGraph 报告字段，哪些数字是传输/调用统计；
3. MCP 对象 JSON 相对 CLI 增加多少 UTF-8 bytes（**并按字符串转义 / 数组结构 / 对象字段 / CLI 尾换行四项归因**）；
4. `T_wire_payload` 增量是多少（**须加注：含 JSON 编码放大，不等于模型实际收到的语义 token 量**）；
5. `T_context` 增量是多少（主口径 text-only；信封口径仅作对照）；
6. 哪些 token 数是近似估算，哪些 provider usage 在本实验中不可得；
7. **R1 新增**：20 次调用的索引指纹是否全程一致（结果可复现的前提）。
