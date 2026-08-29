# CodeGraph CLI 与 MCP 运行结果对比报告

## 结论摘要

本次验证使用同一查询、同一索引和同一 `maxFiles=1` 参数，CLI 与 MCP 返回的逻辑正文在移除 CLI 尾部一个换行后 **10/10 次完全一致**。可见差异只有传输表示：CLI stdout 多 1 个换行，MCP 额外有 `content[]` 和 `CallToolResult` JSON 包装。

MCP 的 payload JSON 比 CLI stdout 多 `327 bytes`，但这不等于模型多收到 `327` 个语义 token。按 ForgeAgent 的近似估算，text-only 模型上下文只增加 `5 tokens`；把 MCP 对象 JSON 当作上下文的对照口径增加 `28 tokens`，不作为模型实际账单结论。

## 实验配置

| 项目 | 设置 |
|---|---|
| 查询 | `Runtime set_state` |
| 项目路径 | `/Users/admin/Code/llm-agent/ForgeAgent` |
| CodeGraph | `1.6.0` |
| CLI 参数 | `explore --no-color --max-files 1` |
| MCP 参数 | `serve --mcp --path <repo> --no-watch` |
| 执行顺序 | `(CLI, MCP)` 交替 10 轮，共 20 次调用 |
| MCP session | 单 session 复用全部 10 次调用 |
| Provider LLM | 未调用，账单 token 为 `N/A` |

索引状态指纹在 11 个采样点全部一致。当前采样使用的索引为 354 files、10,295 nodes、35,241 edges，`pendingChanges` 为零；索引报告 `builtWithExtractionVersion=24`、当前版本为 25 且 `reindexRecommended=true`。这不影响两条路径的相对比较，但结果不应解释为重建最新索引后的绝对基线。

## 输出细节

| 指标 | CLI | MCP | 差异/说明 |
|---|---:|---:|---|
| 调用次数 | 10 | 10 | 实验常量 |
| `reported_symbols` | 8 | 8 | `Found 8 symbols` |
| `reported_files` | 1 | 1 | `across 1 file` |
| source 行数 | 55 | 55 | 代码围栏内带行号行数 |
| Blast radius 条目 | 4 | 4 | 报告段落条目数 |
| Not shown 条目 | 8 | 8 | 报告段落条目数 |
| 正文字符数 | 5,007 | 5,006 | CLI 多一个尾部换行 |
| 正文 UTF-8 bytes | 5,030 | 5,029 | CLI 多 1 byte |
| 原始正文精确比较 | `false` | `false` | 首个差异 offset `5006` |
| 移除 CLI 一个换行后 | `true` | `true` | 10/10 轮一致 |

**判断：** CodeGraph 的符号、文件、源代码和调用关系细节没有路径差异；差异属于 CLI 输出格式与 MCP 文本项边界。

## Payload 字节对比

MCP 侧使用 `CallToolResult.model_dump(mode="json", by_alias=True, exclude_none=False)` 后进行 `json.dumps(..., ensure_ascii=False)`；该数字是对象 payload 投影，不包含 JSON-RPC `jsonrpc`、`id`、method 和 stdio framing。

| 层级 | CLI | MCP | MCP 相对 CLI |
|---|---:|---:|---:|
| 逻辑正文 | 5,030 | 5,029 | -1 |
| `content[]` JSON | — | 5,284 | +255（相对 MCP 正文） |
| `CallToolResult` JSON | 5,030 | 5,357 | +327 |
| `ensure_ascii=True` 对照 | — | 5,394 | 比 UTF-8 版本再增加 37 |

### MCP 增量归因

| 归因项 | bytes | 计算 |
|---|---:|---|
| 字符串 JSON 转义 | +191 | JSON 字符串值 bytes − 原文 bytes |
| `content[]` 数组/字段结构 | +64 | `content[]` JSON − JSON 字符串值 |
| `CallToolResult` 对象字段 | +73 | 对象 JSON − `content[]` JSON |
| CLI 尾部换行调整 | -1 | CLI stdout 比规范化正文多 1 byte |
| 合计 | **+327** | `191 + 64 + 73 - 1` |

因此不能把 `+327 bytes` 直接称为“MCP 协议多出的代码内容”；其中 `191 bytes` 是转义放大，`137 bytes` 是 JSON 结构字段，且未计入完整 JSON-RPC 帧。

## Token 对比

token 数使用仓库已有的 `estimate_text_tokens` / `estimate_request_tokens`，属于保守近似，不是 provider BPE 账单。

| 口径 | CLI | MCP | MCP - CLI | 含义 |
|---|---:|---:|---:|---|
| `T_result_raw` | 1,421 | 1,420 | -1 | 各自原始正文，CLI 含尾部换行 |
| `T_result_normalized` | 1,420 | 1,420 | 0 | 跨路径逻辑内容 |
| `T_wire_payload` | 1,421 | 1,561 | **+140** | CLI stdout vs `CallToolResult` JSON |
| `T_context` text-only | 1,491 | 1,496 | **+5** | 固定两条 Message，结果使用正文 |
| `T_context` 对象 JSON 对照 | 1,607 | 1,635 | **+28** | 仅用于观察 payload 包装影响 |

### 解释

1. `T_result_normalized=0` 说明两条路径返回的是同一份逻辑内容。
2. `T_wire_payload=+140` 说明 JSON 转义和结构会增加本地 payload token，但它不是模型实际看到的语义 token 数。
3. 主模型可见口径是 text-only，只有 `+5`；这部分来自 CLI 命令表达与 MCP 工具调用表达的差异。
4. 对象 JSON 对照的 `+28` 将 payload 编码开销带入上下文，仅用于诊断，不应替代宿主实际上下文或 provider usage。

## 稳定性

| 指标 | min | max | median |
|---|---:|---:|---:|
| `reported_symbols` | 8 | 8 | 8 |
| `reported_files` | 1 | 1 | 1 |
| source 行数 | 55 | 55 | 55 |
| Blast radius 条目 | 4 | 4 | 4 |
| Not shown 条目 | 8 | 8 | 8 |
| CLI 正文 bytes | 5,030 | 5,030 | 5,030 |
| MCP 正文 bytes | 5,029 | 5,029 | 5,029 |
| `T_result_normalized` | 1,420 | 1,420 | 1,420 |
| `T_wire_payload`（CLI） | 1,421 | 1,421 | 1,421 |
| `T_wire_payload`（MCP） | 1,561 | 1,561 | 1,561 |
| text-only `T_context`（CLI） | 1,491 | 1,491 | 1,491 |
| text-only `T_context`（MCP） | 1,496 | 1,496 | 1,496 |

## 运行限制

- 本次没有真实模型请求，因此 `TokenUsage.input_tokens`、`output_tokens` 和费用均不可得。
- MCP 使用 stdio 直连并启用 `--no-watch`；运行时没有可用 shared daemon，server 使用 in-process fallback。索引指纹仍保持稳定。
- 报告统计的是 `CallToolResult` payload 对象 JSON，不是完整 JSON-RPC 原始帧；若要测线上的实际 framing，需要额外抓取 stdio 帧。
- CodeGraph 索引建议重建（extraction v24 → v25）；本报告只对比两条路径读取同一索引时的差异。

## 原始证据

- 正式运行目录：`/tmp/codegraph-parity-5pthwjf1`
- 运行命令：

```bash
.venv/bin/python scripts/codegraph_cli_mcp_comparison.py \
  --path /Users/admin/Code/llm-agent/ForgeAgent \
  --repeats 10
```

- 验证器：[codegraph_cli_mcp_comparison.py](../../../scripts/codegraph_cli_mcp_comparison.py)
- 设计文档：[2026-08-29-codegraph-cli-mcp-comparison-design.md](../superpowers/specs/2026-08-29-codegraph-cli-mcp-comparison-design.md)
