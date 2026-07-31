# repair-mcp-progressive-disclosure-baseline 验证报告

- 日期：2026-08-01
- 结论：PASS
- 基线：`8513bef069ef75ec7b9959a3112e0863722239a0`
- 验证 HEAD：`e08de432f7cd34094e4478f69ee9492a483a6e46`
- 分支处理：保留 `feature/20260801/m45-baseline-reconciliation`，继续执行 M45 后续顺序 change

## 结果总览

| 维度 | 结果 | 证据 |
|---|---|---|
| 完整性 | PASS | OpenSpec 任务 9/9 完成；requirements 3/3 实现 |
| 正确性 | PASS | scenarios 9/9 有实现与回归证据；真实 manager 边界可执行 |
| 一致性 | PASS | 实现遵循 manager-owned snapshot、无网络查询和有界目录设计 |
| 安全性 | PASS | 无新增 secret、raw exception、绝对路径或实际 MCP 调用泄漏 |
| 兼容性 | PASS | MCP manager/tool 260 项、Task/CLI 330 项聚焦回归通过 |

## 需求映射

### 有界 MCP 目录

- `src/forgeagent/mcp_manager.py` 的 `tools_prompt()` 只渲染公开 server/tool、160 字符单行摘要和权限提示，并指向 `MCPDescribe`。
- `tests/test_mcp_manager.py::test_tools_prompt_is_bounded_directory_without_input_schema` 覆盖多行、Unicode 控制字符、超长描述、schema 不进入 prompt 和两类权限提示。
- 既有无工具测试保持空 prompt，Task prompt 和 CLI 回归均通过。

### MCPDescribe 只读详情

- `MCPManager.describe_tool()` 只遍历当前 `list_tools()` 快照，精确匹配并返回深拷贝；未知或 unavailable 条目返回 `None`。
- `tests/test_tools.py::test_mcp_describe_uses_real_manager_snapshot_without_dispatch` 使用真实 manager，并把 `_submit` 替换为失败探针，证明已知、重复和未知查询均不访问 event loop。
- `tests/test_tools.py::test_mcp_describe_bounds_oversized_description_and_schema` 证明描述限界为 2000 字符、过大 schema 降为 `{}`。
- `tests/test_mcp_manager.py::test_describe_tool_reads_available_snapshot_and_returns_deep_copy` 证明返回对象不可污染 manager 快照。

### 既有 MCP 与 CLI 兼容

- 生产改动未触及 `call_tool()`、确认 gate、receipt、失败分类、raw identity 路由或 CLI 渲染。
- MCP manager/tool 聚焦回归：`260 passed`。
- Task/CLI 聚焦回归：`330 passed`。

## 门禁证据

- `uv run pytest -q`：`2698 passed, 11 skipped in 175.38s`。
- `uv run ruff check .`：通过。
- `uv run ruff format --check .`：`144 files already formatted`。
- `uv build`：成功生成 sdist 和 wheel；未上传。
- `openspec validate --all --strict`：`30 passed, 0 failed`。
- `git diff --check 8513bef...HEAD`：通过。

## 审查记录

首次完整验证发现详情长度越界和重复读取场景缺少直接测试，已自动回退 build 并补齐；第二次全量验证通过。两轮最终自审未发现模糊、错误、过度保守、前后不一致或遗漏，也没有未解决的 CRITICAL、WARNING 或 SUGGESTION。

## 发布边界

本 change 未执行 PyPI、tag、push 或发布自动化。`uv build` 只在本地验证打包能力。
