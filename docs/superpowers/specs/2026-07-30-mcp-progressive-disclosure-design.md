---
comet_change: mcp-progressive-disclosure
role: technical-design
canonical_spec: openspec
status: draft
archived-with: 2026-07-30-mcp-progressive-disclosure
status: final
---

# MCP Progressive Disclosure 技术设计

## 结论

将 MCP system prompt 从“全量描述”收敛为“有界目录”，并增加只读 `MCPDescribe` 按需返回当前工具详情。该方案复用现有 discovery masking、ToolRegistry、ToolOutcome 截断与 MCP 调用安全门，不改变 server 生命周期、确认、receipt 或 CLI 完整诊断。

## 现状与问题

`MCPManager.tools_prompt()` 当前按 server 输出所有工具的完整 description；schema 仍由 manager 保存并可由 CLI 查看，但模型首轮并不需要所有参数细节。随着 MCP 工具增加，system prompt 预算与不可信外部文本注意力面线性增长。

## 方案

1. `tools_prompt()` 仅输出 public server label、工具名、单行短摘要、auto-approved/confirmation required 权限提示，并说明描述可通过 `MCPDescribe` 获取。
2. `MCPManager.describe_tool(server, tool)` 从当前已 available 的 `MCPToolInfo` 快照读取，不连接 MCP loop，不做 SDK 调用。
3. `MCPDescribeArgs` 校验 `{server, tool}`；`MCPDescribe` 返回有界 description、JSON-like input schema 和权限提示。未知条目返回失败 outcome；结果不进入确认门，不创建 receipt。
4. `/mcp tools` 继续调用 `list_tools()`，展示完整 masked 工具描述和既有诊断字段，因此 CLI 诊断能力不缩水；schema 保留在 manager 快照并由详情工具按需返回。

## 安全边界

- 目录和详情只使用 discovery 已 masking 的 public projection，不建立 raw metadata 回退路径。
- 描述文本、schema 和 continuation 都有固定上限；非 JSON-like schema 返回空 schema。
- `MCPDescribe` 只读取内存快照；它不能启动 server、重连、执行工具或改变状态。
- 真正的 `MCP` 调用仍由原有 `autoApprove`、confirmation、external-action receipt 和失败恢复策略处理。

## 明确不做

不引入 Cloudflare MCP Code Mode（隔离 Worker 中运行组合代码）、Worker、远程目录缓存、自动工具选择/执行、新 endpoint、配置面、依赖或发布动作。

## 验证策略

先写测试验证目录长度/无 schema 泄漏、详情查找、未知工具、secret masking、重复请求确定性和 MCP/CLI 兼容；再实现最小改动。最终运行专项与全量 pytest、Ruff、格式检查、`uv build`、OpenSpec strict，并进行两轮一致性与遗漏自评。

