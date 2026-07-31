# Comet Design Handoff

- Change: repair-mcp-progressive-disclosure-baseline
- Phase: design
- Mode: compact
- Context hash: 07e0987d1351804fb7492de72a840932d34ebcf7b1cc4369cee360cb79848f07

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/repair-mcp-progressive-disclosure-baseline/proposal.md

- Source: openspec/changes/repair-mcp-progressive-disclosure-baseline/proposal.md
- Lines: 1-28
- SHA256: bbfb27e6b5e477727e69d92870fbc05ea75e35e8e354a7f3267a39eb6b1da8bc

```md
## Why

M44 基线注册了 `MCPDescribe` 并让工具实现调用 `MCPManager.describe_tool()`，但实际管理器缺少该方法，系统提示也退回一次性注入完整描述。现有测试使用自带该方法的假对象，未覆盖真实管理器调用链，因此 M30 的“渐进披露已完成”声明与可执行代码不一致。

## What Changes

- 恢复 `MCPManager.describe_tool(server, tool)`，只读取当前可用、已脱敏的 discovery 快照，不连接服务器或执行动作。
- 恢复有界 MCP 目录：只公开稳定服务器标签、工具名、单行有界摘要和确认提示，不注入完整 schema。
- 增加真实 `MCPManager` 与 `MCPDescribeTool` 的集成回归，防止 fake 测试再次掩盖接口断裂。
- 恢复 M30 的主规格与验证证据入口；保持现有 MCP 调用、确认、receipt、CLI 完整列表和 masking 行为。
- 不新增依赖，不改变 MCP 线协议，不吸收主工作区其他未提交改动。

## Capabilities

### New Capabilities

- `mcp-progressive-disclosure`: 定义有界 MCP 目录和只读按需详情查询的可执行契约。

### Modified Capabilities

无。现有 `mcp-resilience` 已要求目录与详情使用同一安全投影，本 change 只恢复缺失实现并补齐专属主规格。

## Impact

- 代码：`src/forgeagent/mcp_manager.py`。
- 测试：`tests/test_mcp_manager.py`、`tests/test_tools.py`，必要时覆盖 Task prompt 集成。
- 规格：新增 `mcp-progressive-disclosure` 主能力，继续依赖既有 `mcp-resilience` 安全要求。
- 兼容性：无公开 API 删除或格式破坏；CLI `/mcp tools` 继续显示完整、安全投影后的 discovery 信息。

```

## openspec/changes/repair-mcp-progressive-disclosure-baseline/design.md

- Source: openspec/changes/repair-mcp-progressive-disclosure-baseline/design.md
- Lines: 1-56
- SHA256: f26dd9fb2f1cd2115f08d68cf127706b08885c715a919c50bd832f30532d4345

```md
## Context

M30 的协议模型和 `MCPDescribeTool` 已进入 M44 代码，但 manager 查询方法、目录边界测试、专属主规格和归档证据没有进入同一 Git 基线。结果是 registry 会向模型公开 `MCPDescribe`，真实 manager 却无法执行该调用；工具层 fake 测试因为自行提供 `describe_tool()` 而保持绿色。

本 change 把修复限制在 discovery 公开投影层。现有连接、调用、确认、外部动作 receipt、CLI 诊断和内部 raw identity 路由均不改变。

## Goals / Non-Goals

**Goals:**

- 让真实 `MCPManager` 完整实现已被工具层消费的只读查询接口。
- system prompt 只注入有界目录，详情通过 `MCPDescribe` 按需读取。
- 用真实 manager 集成测试证明接口、边界和无副作用语义。
- 恢复无占位的 `mcp-progressive-disclosure` 主规格和可追溯验证证据。

**Non-Goals:**

- 不修改 MCP SDK 生命周期、协议、确认、receipt 或错误分类。
- 不新增缓存、分页、自动选工具、Code Mode、Worker、HTTP 路由或依赖。
- 不从主工作区批量复制未审查文件。

## Decisions

### 1. manager 是 discovery 快照的唯一所有者

`MCPManager.describe_tool(server, tool)` 遍历 `list_tools()` 的当前 public `MCPToolInfo`，只匹配精确 public server/tool pair，并返回 deep copy。查询不提交 coroutine、不连接 server、不触发确认或 receipt。相较于让工具直接读取 `_states`，该方案保持 manager 封装和当前 available 过滤语义。

### 2. 恢复最小有界目录而非新抽象

`tools_prompt()` 继续由 manager 渲染。描述先把 Unicode 控制/格式/代理/行分隔字符投影为空格，再折叠空白并截取 160 字符；每项附加 `auto-approved` 或 `confirmation required`。不新建 helper 模块，因为逻辑只服务 manager prompt 且不足以形成共享抽象。

### 3. 测试必须跨越真实接口边界

保留工具的局部安全投影测试，同时增加使用真实 `MCPManager` 的测试：构造 available discovery 快照，通过 `MCPDescribeTool.run()` 查询并断言成功、无 receipt、无确认和无网络调度。该测试会在 manager 方法再次缺失时直接失败，避免 fake 自洽。

### 4. 历史材料仅作为候选证据

主工作区中 M30 代码、测试、规格和归档只读比较。只把与本 proposal/spec 一致的最小差异重新实现到 M45 工作区；`TBD` Purpose、过期计数和无法证明的完成声明不复制。

## Risks / Trade-offs

- **风险：目录摘要截断丢失参数细节。** → 目录明确指向 `MCPDescribe`，完整 schema 只按需返回。
- **风险：同名 raw identity 与 public label 混淆。** → 查询只接受当前 `list_tools()` 中已经过 manager 安全投影的精确 pair。
- **风险：恢复历史实现时带入无关脏改动。** → 只修改 manager、相关测试和本 change 产物，并逐文件 diff。
- **代价：模型可能多消耗一次详情调用。** → 这是渐进披露的预期成本，不增加自动调用或缓存复杂度。

## Migration Plan

1. 先增加真实 manager 集成失败测试并确认因缺少方法失败。
2. 恢复 manager 查询和有界目录最小实现，运行 MCP/Tool/Task/CLI 聚焦回归。
3. 同步无占位主规格，执行全量测试、Ruff、format、build 和 OpenSpec strict。
4. 若任何兼容测试失败，回滚本 change 提交即可；无数据或状态迁移。

## Open Questions

无。未来目录分页或动态 schema 版本化必须基于真实规模/一致性需求另立 change。

```

## openspec/changes/repair-mcp-progressive-disclosure-baseline/tasks.md

- Source: openspec/changes/repair-mcp-progressive-disclosure-baseline/tasks.md
- Lines: 1-17
- SHA256: b98243ec0bdc0259debe285f2d06ff311dcc493333e83876f5069175ff297753

```md
## 1. 缺陷复现

- [ ] 1.1 增加使用真实 `MCPManager` 调用 `MCPDescribeTool` 的集成测试，不使用 fake manager，并确认测试因 manager 查询契约缺失而失败
- [ ] 1.2 增加 MCP 描述包含多行、控制字符和超长文本时的有界目录测试

## 2. 最小修复

- [ ] 2.1 增加只读 `MCPManager.describe_tool()` 快照查询，按公开 server/tool 精确匹配并返回深拷贝
- [ ] 2.2 渲染带权限提示和按需 `MCPDescribe` 指引的有界单行 MCP 目录
- [ ] 2.3 保持现有 MCP 调用路由、确认、receipt、脱敏和 CLI 诊断行为不变

## 3. 证据与验证

- [ ] 3.1 运行 MCP manager、tool、task 和 CLI 聚焦回归测试
- [ ] 3.2 同步无占位文本的 `mcp-progressive-disclosure` 权威规格
- [ ] 3.3 运行全量 pytest、Ruff check、Ruff format、包构建和 OpenSpec strict 门禁
- [ ] 3.4 记录已验证证据并归档 change，不触发 PyPI、tag、push 或发布自动化

```

## openspec/changes/repair-mcp-progressive-disclosure-baseline/specs/mcp-progressive-disclosure/spec.md

- Source: openspec/changes/repair-mcp-progressive-disclosure-baseline/specs/mcp-progressive-disclosure/spec.md
- Lines: 1-49
- SHA256: f318fb8f2007382251aa6944bbf3fabe8e4dfd7bad262c46e390d57e0b830c99

```md
## ADDED Requirements

### Requirement: MCP prompt uses a bounded tool directory

ForgeAgent SHALL inject only a bounded MCP directory into the task system prompt. Each advertised entry MUST use the manager-owned public server label, tool name, one-line bounded summary, and a permission hint; the prompt MUST identify descriptions as external data and MUST explain that `MCPDescribe` can provide details on demand. Full input schemas MUST NOT be injected into this directory.

#### Scenario: Directory lists available tools
- **WHEN** one or more MCP tools are available
- **THEN** the system prompt lists each public server/tool pair with a bounded summary and tells the model how to request details

#### Scenario: Long discovery metadata is bounded
- **WHEN** a server returns a very long, multiline, or control-character-bearing description
- **THEN** the directory normalizes it to one line and truncates it within the configured summary limit

#### Scenario: No MCP tools are available
- **WHEN** no MCP tool is available
- **THEN** the MCP prompt section is empty and no detail lookup instruction is advertised

### Requirement: MCPDescribe returns one safe tool detail

ForgeAgent SHALL expose a read-only `MCPDescribe` tool with arguments `{server, tool}`. It MUST read only the current available manager-owned public discovery snapshot, return a bounded masked description and JSON-like input schema, and MUST NOT connect to a server, execute an external action, request confirmation, or create an external-action receipt.

#### Scenario: Known tool is described through the real manager
- **WHEN** `MCPDescribe` receives an available public server/tool pair through a real `MCPManager`
- **THEN** it returns the tool description, bounded input schema, and current approval hint without network, confirmation, or receipt side effects

#### Scenario: Unknown tool is requested
- **WHEN** the server/tool pair is absent or unavailable
- **THEN** the tool returns a failed structured outcome with a bounded retry instruction and does not access the MCP loop

#### Scenario: Detail metadata exceeds limits
- **WHEN** the description or schema exceeds its configured bound or cannot be serialized safely
- **THEN** the result remains bounded and uses an empty schema or truncation continuation instead of exposing raw data

#### Scenario: Duplicate detail requests are deterministic
- **WHEN** the same `{server, tool}` is requested repeatedly without a discovery change
- **THEN** each response is derived from the same snapshot and no new network, connection, confirmation, receipt, or external action occurs

### Requirement: Existing MCP calls and CLI diagnostics remain compatible

ForgeAgent SHALL keep the existing `MCP` ToolCall `{server, tool, arguments}` routing, confirmation, receipt, failure, and masking semantics unchanged. CLI `/mcp tools` MUST continue to display the complete available masked discovery listing, independent of the bounded system-prompt directory.

#### Scenario: Existing MCP call remains routable
- **WHEN** the model calls an advertised tool through `MCP`
- **THEN** the original internal server/tool identity reaches existing routing and the existing confirmation and receipt policy applies

#### Scenario: CLI requests full listing
- **WHEN** a user runs `/mcp tools`
- **THEN** the CLI displays the complete masked descriptions and existing diagnostic fields from the manager while schema remains available through `MCPDescribe`

```
