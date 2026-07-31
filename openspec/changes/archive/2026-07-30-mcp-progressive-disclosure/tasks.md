# 实施任务

## 1. 契约与 manager 投影

- [x] 1.1 增加有界 MCP 目录/详情常量，以及只读当前快照的 `MCPManager.describe_tool()` 投影。
- [x] 1.2 将 `tools_prompt()` 改为渲染有界目录、权限提示和 `MCPDescribe` 指引，不注入完整 schema。
- [x] 1.3 增加 `MCPDescribeArgs` 与只读 `MCPDescribe` 工具，仅在启用 MCP 的 registry 中注册。

## 2. 测试优先与兼容性

- [x] 2.1 先增加目录边界、无 schema 泄露、详情查询、未知工具、掩码和重复请求确定性的失败测试。
- [x] 2.2 增加既有 `MCP` 调用和 CLI `/mcp tools` 完整清单的兼容性测试。
- [x] 2.3 运行专项测试，再修正实现直到全部通过；不得改变 receipt/confirmation 行为。

## 3. 文档与验证

- [x] 3.1 更新 MCP 使用文档与 threat-model，记录目录/详情边界和明确不做的能力。
- [x] 3.2 补齐 design/plan/verification 证据，并运行全量 pytest、Ruff、格式检查、build 和 OpenSpec strict 校验。
- [x] 3.3 最终进行两轮自评，检查模糊、错误、过度保守、前后不一致和遗漏；发现问题立即修复并复验。保持 PyPI 发布暂停。
