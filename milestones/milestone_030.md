# 里程碑 M30: MCP 渐进披露

- 状态: 已完成
- 起止: 2026-07-30 ~ 2026-07-30
- 对应 ACTION_PLAN 行: M30（见该文件 §四 里程碑表）
- 前置里程碑: [milestone_029](milestone_029.md)
- 技术设计: [2026-07-30-mcp-progressive-disclosure-design](../docs/superpowers/specs/2026-07-30-mcp-progressive-disclosure-design.md)
- 实施计划: [2026-07-30-mcp-progressive-disclosure](../docs/superpowers/plans/2026-07-30-mcp-progressive-disclosure.md)
- OpenSpec change: [2026-07-30-mcp-progressive-disclosure](../openspec/changes/archive/2026-07-30-mcp-progressive-disclosure/)
- 验证报告: [2026-07-30-mcp-progressive-disclosure-verify](../docs/superpowers/reports/2026-07-30-mcp-progressive-disclosure-verify.md)

## 目标与范围

降低 MCP 全量描述注入 system prompt 的上下文成本和注意力干扰：首轮只提供有界工具目录，需要参数细节时通过只读 `MCPDescribe` 按需读取。范围不含 Code Mode、Worker、远程目录缓存、自动工具选择/执行、新依赖、endpoint、配置面、发布、tag 或 push。

## 方案设计

- `MCPManager.tools_prompt()` 输出 public server label、工具名、单行短摘要、权限提示和 `MCPDescribe` 指引；不注入完整 schema。
- `MCPManager.describe_tool()` 只读当前 available `MCPToolInfo` 快照；`MCPDescribe` 返回有界 masked description/schema/权限提示，未知工具返回结构化失败。
- 详情文本清理 secret 和控制字符；schema 使用安全 JSON 序列化，非 JSON-like、非有限浮点或超长结果降级为空 schema。
- CLI `/mcp tools` 和既有 `MCP` 调用语义保持不变。
- 裁决 M30-1（2026-07-30）：采用“目录 + 按需详情”，拒绝 Code Mode/Worker/远程缓存，避免先建平台再找场景。
- 裁决 M30-2（2026-07-30）：CLI 继续展示完整 masked 工具描述与诊断字段；schema 由 `MCPDescribe` 按需读取，不扩大现有 CLI 输出合同。
- 裁决 M30-3（2026-07-30）：本里程碑只做本地工程验证，不执行外部分发；该目标后续已从路线图移除。

## 子任务清单

- [x] 完成 MCP manager 有界目录和 snapshot-only detail projection
- [x] 完成 `MCPDescribeArgs`、只读 `MCPDescribe` 和 MCP-enabled registry 注册
- [x] 完成目录长度/schema 泄露、未知工具、控制字符、secret masking、重复请求和兼容性测试
- [x] 更新 MCP 使用文档、协议边界和 threat-model
- [x] 完成全量测试、静态检查、构建、OpenSpec strict 和两轮最终自评

## 交付物清单

- [x] `src/forgeagent/mcp_manager.py` — 有界目录、权限提示、snapshot-only `describe_tool`
- [x] `src/forgeagent/protocol.py` — `MCPDescribeArgs`
- [x] `src/forgeagent/tools.py` — 只读 `MCPDescribeTool` 与 MCP-enabled registry 注册
- [x] `tests/test_mcp_manager.py`、`tests/test_tools.py` — 目录/详情边界和兼容回归
- [x] `docs/m7-tools-mcp-survey.md`、`docs/threat-model.md` — 渐进披露与威胁边界
- [x] OpenSpec proposal/design/spec/tasks 与验证报告

## 三次评审

### 技术方案评审

- [x] 方案与综合借鉴清单一致：候选 3 仅在现有 MCP 基础上做最小渐进披露，不升级平台化能力
- [x] 方案明确状态所有权、信任边界、失败语义、兼容策略、证据来源和恢复边界
- [x] 发现并修正规格歧义：CLI 既有输出不承诺 schema；schema 通过 `MCPDescribe` 按需可读

### 代码评审

- [x] 两轮逐文件自审：检查 registry 可见性、MCP 调用/receipt/confirmation 不变量、secret/control-char/schema 边界
- [x] 发现问题已修复：OpenSpec delta header、zh-CN 任务门禁、CLI schema 规格过度承诺、详情控制字符规范化
- [x] 已尝试委派独立 reviewer；当前会话未收到可用反馈，以两轮主 Agent 自审、全量回归和 OpenSpec 门禁作为本次代码评审证据

### 验收评审

- [x] 专项 MCP/工具/协议/Task/CLI 回归：`612 passed`
- [x] 完整回归：`2451 passed, 10 skipped`
- [x] `uv run ruff check .`、`uv run ruff format --check .`、`git diff --check` 通过
- [x] `uv build` 通过，产出 `dist/forgeagent-0.1.0.tar.gz` 与 `dist/forgeagent-0.1.0-py3-none-any.whl`
- [x] `openspec validate --all --strict --no-interactive`：`26 passed, 0 failed`
- [x] 未执行外部分发；原 `publish-v0-1-0` 后续已撤销并归档

## 遗留问题

- [x] 正式外部分发目标已移除 — 影响：保留本地/RC 工程证据，不产生公开发布证据 — 处理：原发布 change 已撤销并归档，无恢复路径

## 续接指引

M30 已完成实现、本地验证和 Comet verify/archive。当前分支保留 M29、M30 和用户既有未提交文件，均未自动提交。下一阶段应读取本文件与
`milestones/latest`，再按借鉴清单候选 4“Duo/Triad 结构化交接”单独建立 change；不得把候选顺序直接当执行令。外部分发不在当前路线图。

## M45 对账注记

- 本文件于 M45 从已验证历史工件恢复；原测试计数只对应当时快照，当前 HEAD 由 M45 全量门禁证明。
- M44 集成基线曾缺失 manager 查询契约；M45 已由 [`repair-mcp-progressive-disclosure-baseline`](../openspec/changes/archive/2026-07-31-repair-mcp-progressive-disclosure-baseline/) 重建并验证。
- 包索引发布、正式 tag 和发布自动化仍不在路线图；经用户授权的普通开发分支 push 仅用于版本控制交接。
- 当前基线以 `ACTION_PLAN.md` 和 `milestones/latest` 为准，本文件中的旧“续接指引”只保留历史语境。
