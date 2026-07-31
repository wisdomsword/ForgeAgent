---
comet_change: repair-mcp-progressive-disclosure-baseline
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-31-repair-mcp-progressive-disclosure-baseline
status: final
---

# MCP 渐进披露基线修复技术设计

## 1. 问题边界

M45 的起始基线已经注册 `MCPDescribe`，且工具实现调用 `ctx.mcp.describe_tool()`，但真实 `MCPManager` 没有该方法。局部 fake 测试自行提供同名方法，因此无法证明 registry、工具和 manager 的真实组合可执行。与此同时，system prompt 仍可能一次性携带完整 MCP 描述，偏离渐进披露契约。

修复只覆盖 discovery 的公开投影层。MCP 连接生命周期、内部 raw identity、实际调用、确认、外部动作 receipt、失败分类和 CLI 诊断不在本 change 的修改范围内。

## 2. 所有权与数据流

`MCPManager` 继续是 server 状态和 discovery 快照的唯一所有者：

1. server discovery 更新内部状态；
2. `list_tools()` 产生当前可用、已使用公开 server label 的 `MCPToolInfo` 快照；
3. `tools_prompt()` 从该快照渲染有界目录；
4. `describe_tool(server, tool)` 从同一快照精确查找并返回深拷贝；
5. `MCPDescribeTool` 仅消费公开查询结果并执行已有的输出限界和安全投影。

不允许工具层直接访问 `_states`。这避免 discovery 可见性规则在两个模块中分叉，也防止调用者修改 manager 持有的模型对象。

## 3. 查询契约

`describe_tool()` 是同步、只读、无副作用方法。输入必须同时精确匹配公开 server label 和 tool name；未知或不可用条目返回 `None`。每次调用从当前 `list_tools()` 结果派生，不建立额外缓存，不提交 coroutine，不连接 server，不请求用户确认，也不创建 external-action receipt。

返回值使用 model deep copy，使调用方无法通过修改返回对象污染后续目录或详情读取。重复读取在 discovery 未变化时应得到等价结果。

## 4. 有界目录

目录摘要沿用 manager 内部的最小 helper：

- 将 Unicode `Cc`、`Cf`、`Cs`、`Zl`、`Zp` 类字符投影为空格；
- 折叠连续空白并去除首尾空白；
- 每个描述最多保留 160 个字符；
- 每项仅包含公开 server、tool、摘要和 `auto-approved` / `confirmation required`；
- 目录头把 MCP 描述声明为外部数据，并指向 `MCPDescribe` 获取详情；
- 不把完整 input schema 注入 system prompt。

当没有可用工具时返回空字符串，不投放无意义的详情指引。

## 5. 兼容与安全

现有 `MCP` ToolCall 格式和调用路径不变。`MCPDescribe` 不复用实际调用路径，因为只读 metadata 查询不应获得外部动作语义。CLI `/mcp tools` 仍使用完整、安全投影后的 discovery 列表，不能被 160 字符的 prompt 限制截断。

公开目录和详情只能包含 manager 已经投影出的 public server label。原始 server identity、secret、raw exception 和未限界的外部描述不得新增到输出或日志。

## 6. 测试与回滚

TDD 的 RED 证据必须来自真实 `MCPManager` 与 `MCPDescribeTool` 的组合，并因缺少 `describe_tool()` 明确失败。GREEN 后断言成功结果没有 receipt、没有确认请求，且测试不启动 MCP event loop 或网络连接。

目录测试覆盖多行、控制字符、超长描述、权限提示和无工具状态。兼容回归覆盖 manager、tools、Task prompt 和 CLI。最终门禁为全量 pytest、Ruff check、Ruff format、包构建和 OpenSpec strict。

本 change 无数据迁移。若兼容测试失败，回滚该 change 的代码提交即可；不得通过恢复一次性完整 schema 注入来规避失败。
