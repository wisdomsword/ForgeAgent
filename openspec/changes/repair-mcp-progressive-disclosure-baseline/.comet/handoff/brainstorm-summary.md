# Brainstorm Summary

- Change: repair-mcp-progressive-disclosure-baseline
- Date: 2026-08-01

## 确认的技术方案

由 `MCPManager` 正式拥有公开 discovery 快照的只读查询契约。`describe_tool()` 只遍历当前 `list_tools()` 投影，按公开 server/tool 精确匹配并返回深拷贝；`tools_prompt()` 只渲染有界单行摘要、权限提示和按需 `MCPDescribe` 指引。工具层不读取 manager 私有状态，也不新增 registry adapter、缓存、网络请求或依赖。

## 关键取舍与风险

候选方案包括工具层直接读取 `_states`、registry 侧补适配器、manager 正式提供查询契约。前两者会复制状态所有权或突破封装，因此采用第三种。摘要截断可能减少提示中的细节，但完整 schema 可由 `MCPDescribe` 按需读取。历史主工作区仅作为候选证据，不能替代 M45 分支上的重新验证。

两轮自审均未发现需要扩大范围的理由：查询必须保持无网络、无确认、无 receipt；MCP 调用路由、CLI 完整列表和外部动作语义保持不变。

## 测试策略

先用真实 `MCPManager` 驱动 `MCPDescribeTool` 写失败测试，确认当前分支因缺少查询方法而失败；再增加长文本、多行和 Unicode 控制字符的目录边界测试。实现后运行 MCP manager、tool、Task prompt 和 CLI 聚焦回归，再运行全量 pytest、Ruff、format、包构建和 OpenSpec strict。

## Spec Patch

无。现有 delta spec 已包含可执行的有界目录、真实 manager 查询、无副作用和兼容性场景。
