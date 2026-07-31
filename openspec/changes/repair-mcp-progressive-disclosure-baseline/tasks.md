## 1. 缺陷复现

- [x] 1.1 增加使用真实 `MCPManager` 调用 `MCPDescribeTool` 的集成测试，不使用 fake manager，并确认测试因 manager 查询契约缺失而失败
- [x] 1.2 增加 MCP 描述包含多行、控制字符和超长文本时的有界目录测试

## 2. 最小修复

- [x] 2.1 增加只读 `MCPManager.describe_tool()` 快照查询，按公开 server/tool 精确匹配并返回深拷贝
- [x] 2.2 渲染带权限提示和按需 `MCPDescribe` 指引的有界单行 MCP 目录
- [x] 2.3 保持现有 MCP 调用路由、确认、receipt、脱敏和 CLI 诊断行为不变

## 3. 证据与验证

- [x] 3.1 运行 MCP manager、tool、task 和 CLI 聚焦回归测试
- [ ] 3.2 同步无占位文本的 `mcp-progressive-disclosure` 权威规格
- [ ] 3.3 运行全量 pytest、Ruff check、Ruff format、包构建和 OpenSpec strict 门禁
- [ ] 3.4 记录已验证证据并归档 change，不触发 PyPI、tag、push 或发布自动化
