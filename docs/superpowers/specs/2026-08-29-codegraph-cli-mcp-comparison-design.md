# CodeGraph CLI 与 MCP 对照验证设计

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

两条路径均使用 `max-files=1`，并读取同一份已经建立的 CodeGraph 索引和 daemon。CLI 必须使用 `--no-color`，避免 ANSI 转义序列影响比较。

CLI 命令：

```bash
codegraph --no-color explore \
  --path /Users/admin/Code/llm-agent/ForgeAgent \
  --max-files 1 'Runtime set_state'
```

MCP 调用：

```text
codegraph_explore({
  projectPath: "/Users/admin/Code/llm-agent/ForgeAgent",
  maxFiles: 1,
  query: "Runtime set_state"
})
```

两条路径各执行 10 次。每次执行前确认索引状态没有变化；若索引变化，整组结果标记为不可比并重新开始。实验只保存 stdout、MCP 原始 `CallToolResult` 和解析后的文本，不保存环境变量或密钥。

## 输出层次与判定

### 逻辑正文

- CLI 的逻辑正文是完整 stdout。
- MCP 的逻辑正文是 `CallToolResult.content` 中所有 `type == "text"` 项按顺序拼接的文本。
- 首先做原始字符串和 UTF-8 bytes 精确比较。
- 然后只移除 CLI 末尾的换行（等价于 `rstrip("\\n")`），再次比较。不得使用 `strip()`，因为它会隐藏正文边界上的空格差异。

原始比较失败不等于 CodeGraph 内容不同；必须同时报告失败位置和归一化比较结果。

### 传输包装

分别记录：

- CLI stdout 的 UTF-8 字节数；
- MCP `content[].text` 的 UTF-8 字节数；
- MCP 完整 `CallToolResult` JSON 序列化后的 UTF-8 字节数；
- CLI/MCP 的 stderr 或诊断日志不计入上述正文和 wire 数字。

CLI 是进程 stdout，MCP 是结构化 tool result；两者的 wire 数字不能直接解释为“源代码内容大小”。

### 报告字段

从共同正文中分别提取以下字段，不做跨字段求和：

- `reported_symbols`：`Found N symbols` 中的 `N`；
- `reported_files`：`across F files` 中的 `F`；
- `source_line_count`：代码围栏内带行号的源代码行数；
- `blast_radius_entry_count`：Blast radius 区域的条目数；
- `not_shown_entry_count`：`Not shown above` 区域的条目数；
- `invocation_count`：每条路径的命令或 MCP 工具调用次数。

示例中当前一次基线报告为 `8 symbols across 1 file`；这个值用于检查输出稳定性，不写死为产品契约。

## Token 口径

使用仓库已有的 `forgeagent.context` 估算函数：

- `estimate_text_tokens(text)`：结果文本近似 token 数；
- `estimate_request_tokens(messages, config)`：带消息和请求 framing 的近似 token 数。

记录三列：

1. `T_result`：只对逻辑正文估算，表示 CodeGraph 内容本身；
2. `T_wire`：对 CLI stdout 或 MCP 完整 JSON 估算，表示传输层包装；
3. `T_context`：把固定 system prompt、固定查询、路径、命令/工具标识和对应结果拼入相同结构的 `Message` 请求后估算，表示模型可见上下文的受控代理。

`T_context` 必须使用同一固定前缀和同一序列化模板；唯一变化是 CLI 与 MCP 的命令/工具标识、参数表示和结果包装。报告中同时给出包装增量：`delta = MCP - CLI`。

这些数字是仓库定义的保守近似，不是特定 provider 的 BPE 账单。因为基础实验没有模型请求，`TokenUsage.input_tokens`、`output_tokens` 和 provider 费用统一记为 `N/A`。若未来增加真实模型回放，provider usage 作为独立列，不替代前三列。

## 重复运行与稳定性

每条路径运行 10 次，报告每个数值的 `min / max / median`。对正文和报告字段做确定性检查：

- 10 次归一化正文必须完全一致；
- `reported_symbols`、`reported_files`、各类条目数必须稳定；
- 若仅 CLI 末尾换行不同，记录为 transport formatting 差异；
- 若归一化正文不同，停止汇总并检查索引同步、daemon 状态和查询参数。

不把进程启动时间、daemon 延迟或终端渲染时间纳入本案例结论；它们属于另一个性能实验。

## 结果表

最终报告使用以下固定列：

| 指标 | CLI | MCP | 口径 |
|---|---:|---:|---|
| 调用次数 | 10 | 10 | 命令/tool invocation |
| 报告 symbols | 实测 | 实测 | 报告头字段 |
| 报告 files | 实测 | 实测 | 报告头字段 |
| source 行数 | 实测 | 实测 | 带行号代码行 |
| Blast radius 条目 | 实测 | 实测 | 独立计数 |
| 正文 UTF-8 bytes | 实测 | 实测 | CLI stdout / MCP text |
| 完整 wire UTF-8 bytes | stdout | JSON envelope | 含协议包装 |
| `T_result` | 估算 | 估算 | 内容本身 |
| `T_wire` | 估算 | 估算 | 传输表示 |
| `T_context` | 估算 | 估算 | 模型可见代理 |
| provider `TokenUsage` | N/A | N/A | 本实验无 LLM 请求 |

## 已知基线与限制

当前一次实测显示：CLI 与 MCP 的逻辑正文在移除 CLI 结尾换行后相同；CLI stdout 多一个换行；MCP 完整 JSON 比 MCP text 多协议包装字段。该观察用于验证实验设计，不保证所有查询、索引版本或 CodeGraph 版本都相同。

本设计不比较不同模型 tokenizer，不评估 CodeGraph 查询正确性，不衡量 CLI/MCP 延迟，也不把结构化协议包装误称为源代码细节。

## 验收标准

验证完成必须能回答：

1. 两条路径的正文是否精确相同，若不相同，首个差异是什么；
2. 哪些数字是 CodeGraph 报告字段，哪些数字是传输/调用统计；
3. MCP 包装相对 CLI 增加多少 UTF-8 bytes、`T_wire` 和 `T_context`；
4. 哪些 token 数是近似估算，哪些 provider usage 在本实验中不可得。

