---
change: repair-mcp-progressive-disclosure-baseline
design-doc: docs/superpowers/specs/2026-08-01-mcp-progressive-disclosure-baseline-repair-design.md
base-ref: 8513bef069ef75ec7b9959a3112e0863722239a0
archived-with: 2026-07-31-repair-mcp-progressive-disclosure-baseline
---

# MCP 渐进披露基线修复实施计划

> 按 OpenSpec delta spec 和技术设计执行。生产代码改动前必须先取得真实 `MCPManager` 边界上的 RED 证据。

## 任务 1：复现真实接口断裂

**文件：**
- 修改：`tests/test_tools.py`
- 修改：`tests/test_mcp_manager.py`

1. 使用真实 `MCPManager`、available discovery 快照和现有 `ToolContext` 调用 `MCPDescribeTool.run()`。
2. 断言返回描述、schema、权限提示，且没有 receipt；先运行单测并确认因 `MCPManager.describe_tool` 缺失而失败。
3. 增加目录摘要多行、Unicode 控制字符、超长文本、权限提示和无工具状态用例；先确认旧实现不满足有界目录契约。
4. 将 OpenSpec 任务 1.1、1.2 标记完成并提交测试 RED 证据。

## 任务 2：实现最小 manager 契约

**文件：**
- 修改：`src/forgeagent/mcp_manager.py`

1. 增加目录摘要上限和单行安全投影 helper，仅在 manager 模块内使用。
2. 增加同步只读 `describe_tool(server, tool)`：基于 `list_tools()` 精确匹配并返回深拷贝，未知项返回 `None`。
3. 更新 `tools_prompt()`，只渲染有界摘要、权限提示和 `MCPDescribe` 指引，不注入 input schema。
4. 运行任务 1 的测试并确认 GREEN；运行已有 MCP manager 与 tool 回归，确认调用、确认和 receipt 行为未改变。
5. 标记 OpenSpec 任务 2.1 至 2.3 完成并提交实现。

## 任务 3：兼容与规格验证

**文件：**
- 必要时修改：`tests/test_task.py`、`tests/test_cli.py`
- 更新：`openspec/changes/repair-mcp-progressive-disclosure-baseline/tasks.md`

1. 运行 Task prompt 与 CLI `/mcp tools` 聚焦测试，证明 prompt 有界目录与 CLI 完整诊断边界不冲突。
2. 运行 `uv run pytest tests/test_mcp_manager.py tests/test_tools.py tests/test_task.py tests/test_cli.py -q`。
3. 运行 `uv run ruff check .` 和 `uv run ruff format --check .`。
4. 运行全量 `uv run pytest -q`、`uv build`、所有 OpenSpec strict 校验。
5. 记录实际命令和计数，完成最终代码审查；修复任何正确性、安全、兼容或证据缺口。
6. 标记剩余 OpenSpec 任务完成，提交验证证据并进入 Comet verify。

## 非目标

- 不修改 MCP SDK 生命周期、实际调用协议、确认或 receipt 状态机。
- 不新增依赖、缓存、分页、Code Mode、Worker 或 HTTP 路由。
- 不执行 PyPI、tag、发布自动化；本 change 内也不 push。
