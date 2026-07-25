## Why

P0/P1 收尾后，剩余高优先级债务集中在运行时韧性与验收证据：协作 Evaluator 无法独立执行受控检查，MCP hung-call 仍由永久 skip 代替可执行回归，搜索引擎页面变化缺少运行时 fallback，真实模型与容器能力矩阵也尚未形成最新证据。与此同时，P3 中若干候选增强仍缺少真实需求，不应为了“清单完成”扩大轻量 Agent 的产品面。

## What Changes

- 为协作 Evaluator 增加专用 `RunCheck` 能力：模型只能选择宿主注册的检查 ID，不能提供命令、路径或环境；检查在临时工作副本中以无 shell、固定超时、最小环境和有界输出执行。
- 明确取消与 hard-stuck 的可承诺边界：已有 provider、executor、MCP 超时继续承担在途调用的硬边界；取消阻止后续 round/iteration/role，不能安全终止的宿主线程只允许有界脱离并报告降级，不宣称 Python 线程强杀。
- 把 MCP hung-call 的永久 skip 占位改为快速、确定性、可运行的超时回归。
- 让 `/search` 在首选引擎不可用或解析不到结果时按固定顺序尝试另一个已配置引擎，同时保持 SSRF、代理禁用和错误最小披露。
- 运行并记录可用环境中的真实模型、Evaluator、single/Triad、Docker/container 与 MCP 证据；环境不满足时记录明确阻塞，不伪造通过。
- 对 P3 候选逐项收敛：确认 native tool-call 流式聚合已实现；持久 REPL 历史、语义摘要、音视频输入、响应侧多模态继续延期，并记录可观测触发条件。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `runtime-collaboration`: Evaluator 可使用宿主冻结、隔离执行的检查 ID 获取独立测试证据，且不获得普通 Exec 或任意命令能力。
- `mcp-resilience`: MCP 工具调用超时必须有快速、可重复执行的 hung-call 回归，并保持超时后的 manager 可关闭、后续状态可判定。
- `network-boundary-safety`: 搜索消费者在首选搜索引擎不可用或页面解析失效时使用固定、受限的备用引擎，而不放宽网络安全边界。

## Impact

- 主要影响 `src/forgeagent/collaboration.py`、协作装配入口、`src/forgeagent/mcp_manager.py` 的测试、`src/forgeagent/web_search.py` 及对应测试和文档。
- 不新增第三方依赖、数据库、daemon、公共协作 resume API、任意命令执行 API 或新的 sandbox 档位。
- 默认未注册检查时，Evaluator 工具集合与现有行为保持不变；现有 single/Loop/HTTP 请求 schema 不因本 change 扩大。
