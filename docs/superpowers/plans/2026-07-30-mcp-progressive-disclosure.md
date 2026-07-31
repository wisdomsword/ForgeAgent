---
change: mcp-progressive-disclosure
design-doc: docs/superpowers/specs/2026-07-30-mcp-progressive-disclosure-design.md
base-ref: 6a304bc6273a3acfd06aae81dd265ce3eeef6347
archived-with: 2026-07-30-mcp-progressive-disclosure
---

# MCP 渐进披露实施计划

> 使用 TDD：每个行为先写失败测试并确认 RED，再实现最小代码，最后运行专项验证。

## 约束

- 不修改或推进 `openspec/changes/publish-v0-1-0`；不上传 PyPI、不创建正式 tag、不 push。
- 保留 M29 及用户已有脏工作区改动，不做无关重构。
- 不改变 MCP 外部调用、确认、receipt、生命周期和 CLI 完整清单语义。
- 不新增依赖、endpoint、配置、数据库、Code Mode、Worker 或远程缓存。

## Task 1: MCP manager 目录与详情投影

**Files:** `src/forgeagent/mcp_manager.py`, `tests/test_mcp_manager.py`

- [x] 写失败测试：长/多行 description 目录被规范化和截断，目录不含 input schema，包含权限提示和 `MCPDescribe` 指引。
- [x] 写失败测试：`describe_tool()` 对已知、未知、不可用和重复请求返回确定的 snapshot 结果，不触发 loop/网络。
- [x] 实现最小常量、短摘要 helper、`describe_tool()` 和目录 prompt。
- [x] 运行 `uv run pytest tests/test_mcp_manager.py -q`，确认绿色。

## Task 2: MCPDescribe 协议工具

**Files:** `src/forgeagent/protocol.py`, `src/forgeagent/tools.py`, `tests/test_tools.py`, `tests/test_protocol.py`

- [x] 写失败测试：注册表仅在 MCP-enabled 时包含 `MCPDescribe`；成功、未知、超长 schema、masking 结果均有界。
- [x] 实现 `MCPDescribeArgs`、只读 `MCPDescribe` 和 MCP-enabled registry 注册。
- [x] 运行工具/协议专项测试，确认现有 `MCP` 解析和 receipt/confirmation 测试不回归。

## Task 3: 兼容性与文档

**Files:** `tests/test_cli.py`, `tests/test_task.py`, `docs/m7-tools-mcp-survey.md`, `docs/threat-model.md`

- [x] 增加 CLI `/mcp tools` 完整清单兼容测试和 Task system prompt 目录测试。
- [x] 更新 MCP 使用文档、威胁模型和按需披露边界。
- [x] 运行专项回归测试。

## Task 4: 里程碑验证与收尾

**Files:** `openspec/changes/mcp-progressive-disclosure/tasks.md`, `docs/superpowers/reports/2026-07-30-mcp-progressive-disclosure-verify.md`, `ACTION_PLAN.md`, `milestones/milestone_030.md`, `milestones/latest`

- [x] 运行全量 pytest、Ruff check、Ruff format check、`uv build` 和 OpenSpec strict。
- [x] 进行两轮最终自评：逐项核对 proposal/design/spec/tasks/实现/验证；再检查模糊、错误、过度保守、前后不一致、遗漏和 secret 泄露。
- [x] 发现问题立即修复并重跑受影响验证；更新 M30 里程碑和续接指引，保持 PyPI 发布暂停。

