# Comet Design Handoff

- Change: mcp-progressive-disclosure
- Phase: design
- Mode: compact
- Context hash: 5c4e4dc484b0ebf32beda7478e38ae60069e6bfab376cb76e16fa09ee51a39fc

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/mcp-progressive-disclosure/proposal.md

- Source: openspec/changes/mcp-progressive-disclosure/proposal.md
- Lines: 1-29
- SHA256: 8c5dea7e627f100d4045836beb3445e401e050a50f1875e906e1bce1b5d805ba

```md
## Why

当前 MCP manager 会把所有可用工具的名称和描述一次性注入每个 Task 的 system prompt。server 或工具数量增长时，这会消耗上下文预算、降低模型关注度，并让一次任务承受与目标无关的外部描述；M7 既有 MCP discovery、确认门和收据语义已经足够作为安全基础，适合做最小按需披露。

## What Changes

- 首轮 MCP prompt 只注入有界工具目录：公开 server 名、工具名、短用途摘要和“按需描述”的调用说明。
- 新增只读 `MCPDescribe` 工具：模型按 `{server, tool}` 请求一个已发现工具的详细描述和有界输入 schema；不连接新 server、不执行外部动作、不绕过确认门或收据。
- 复用既有 `MCPToolInfo`、secret masking、上下文预算和 `ToolRegistry`，为描述结果提供有界反馈与继续读取提示。
- 保留 CLI `/mcp tools` 的完整诊断清单，保持既有 MCP ToolCall `{server, tool, arguments}` 兼容。
- 增加离线 token/长度、未知工具、敏感描述/schema、重复请求和普通 MCP 调用兼容测试。
- 不引入 Code Mode、Worker、远程工具目录缓存、自动选择、自动执行或新依赖。

## Capabilities

### New Capabilities

- `mcp-progressive-disclosure`: MCP 工具目录与按需描述协议。

### Modified Capabilities

- `mcp-resilience`: 描述请求只能读取当前 available discovery，不改变 server 生命周期、确认门、receipt 或失败隔离语义。

## Impact

- 运行时：`src/forgeagent/mcp_manager.py`、`src/forgeagent/tools.py`、`src/forgeagent/task.py` 和相关协议/测试。
- 公共模型提示：MCP system-prompt section 从全量描述改为目录；新增注册工具名 `MCPDescribe`。
- 不新增依赖、HTTP endpoint、配置面或数据库；CLI 展示行为保持不变。
- PyPI 发布、正式 tag、远程 push 及 active `publish-v0-1-0` change 不在范围内，继续暂停。

```

## openspec/changes/mcp-progressive-disclosure/design.md

- Source: openspec/changes/mcp-progressive-disclosure/design.md
- Lines: 1-59
- SHA256: c1a600beae7071283528181b9b3eac3c7d5d28512792e770ac698f3a7987c503

```md
# MCP 渐进披露设计

## Context

`MCPManager.tools_prompt()` 当前把所有可用 MCP 工具的完整描述注入每个 Task 的 system prompt。工具数量或描述长度增长时，模型需要在每轮上下文中承担与任务无关的外部文本，既浪费预算，也扩大了不可信描述的注意力面。现有 discovery 已经完成 secret masking、server 生命周期隔离、确认门和副作用收据；本变更只调整披露层，不改变外部调用语义。

## Goals / Non-Goals

### Goals

- 首轮 prompt 提供固定上限的 MCP 工具目录：公开 server、工具名、短用途摘要、权限提示和按需描述指引。
- 提供只读 `MCPDescribe` 工具，按 `{server, tool}` 返回当前 available discovery 的有界详细描述和输入 schema。
- 描述请求不创建连接、不触发外部调用、不绕过确认或 receipt；未知工具返回可恢复的结构化失败。
- 保留 CLI `/mcp tools` 的完整诊断清单和现有 `MCP` ToolCall 路由。
- 复用现有 masking、ToolOutcome 截断和 registry/parser 机制，不引入新依赖。

### Non-Goals

- 不实现 Code Mode、Worker、远程目录缓存、自动工具选择或自动执行。
- 不改 MCP server 连接、重连、required/optional、确认门、收据或错误分类协议。
- 不新增 HTTP endpoint、配置项、数据库、发布动作或 PyPI 变更。

## Decisions

### 1. 目录与详情分离

`tools_prompt()` 只渲染目录。每项包含安全的 public server label、工具名、单行摘要（固定字符上限）和 `auto-approved`/`confirmation required` 权限提示；不渲染完整 schema。目录末尾明确提示模型在需要参数细节时调用 `MCPDescribe`。

`MCPManager.describe_tool(server, tool)` 仅从已发现的当前工具快照读取 `MCPToolInfo`。它不访问 MCP loop，也不接受手工 raw identity 作为回退，不对 unavailable/unknown 工具编造描述。

### 2. MCPDescribe 是低风险只读工具

`MCPDescribe` 注册在 `default_registry(with_mcp=True)`，参数模型为 `MCPDescribeArgs(server, tool)`。成功结果包含有界 description、JSON-like input schema 和当前权限提示；schema 序列化失败或超过上限时返回安全空 schema。未知 server/tool 返回失败 outcome 和下一步指引。该工具不进入 confirmation gate，也不创建 external-action receipt。

### 3. 安全与兼容

`MCPToolInfo` 在 discovery 阶段已完成 masking，因此目录和详情都只使用 public projection。所有新增文本使用现有 `ToolOutcome` bounded feedback；重复请求从同一快照生成确定性结果，不发起网络或连接操作。CLI `/mcp tools` 直接读取 `list_tools()`，继续显示完整 masked 描述和 schema，不受 system prompt 变更影响。

### 4. 预算边界

目录摘要、详情描述和 schema 分别使用常量上限；测试验证长描述、深层 schema、非 JSON-like 值不会突破上限。限制是展示边界，不是对 MCP SDK schema 的重新验证；实际 `MCP` 调用仍由目标 server 自己校验参数。

## Risks / Trade-offs

- 模型首轮看不到参数细节，需要额外一轮 `MCPDescribe`；这是可控的 token/注意力换取，且目录仍保留工具发现能力。
- 摘要截断可能丢失细节，因此详情工具返回更高但有界的上限，并附带“继续使用 MCPDescribe”指引。
- 仅从当前快照读取意味着刚启用但尚未 available 的工具不可描述；这与现有可用工具目录一致，避免描述结果与调用路由不一致。

## Migration Plan

1. 增加协议、manager 查询方法和 `MCPDescribe` 工具测试，先验证失败边界。
2. 切换 `tools_prompt()` 为目录模式，保持 CLI 展示和 `MCP` 调用不变。
3. 更新 MCP 文档、威胁模型和里程碑证据。
4. 运行专项测试、全量测试、Ruff、build、OpenSpec strict；不执行发布。

## Open Questions

- 未来若目录仍过大，应先增加按 server 分页/过滤的明确需求；本变更不预留隐式自动选择协议。
- 若某个 MCP server 需要动态 schema，必须先定义可验证的 snapshot/版本契约，再单独立项。

```

## openspec/changes/mcp-progressive-disclosure/tasks.md

- Source: openspec/changes/mcp-progressive-disclosure/tasks.md
- Lines: 1-19
- SHA256: 5eace9a39e8d57c0f3c2b4101aa7c4f675d455cd25730e38833cc4b9a404f942

```md
# 实施任务

## 1. 契约与 manager 投影

- [ ] 1.1 增加有界 MCP 目录/详情常量，以及只读当前快照的 `MCPManager.describe_tool()` 投影。
- [ ] 1.2 将 `tools_prompt()` 改为渲染有界目录、权限提示和 `MCPDescribe` 指引，不注入完整 schema。
- [ ] 1.3 增加 `MCPDescribeArgs` 与只读 `MCPDescribe` 工具，仅在启用 MCP 的 registry 中注册。

## 2. 测试优先与兼容性

- [ ] 2.1 先增加目录边界、无 schema 泄露、详情查询、未知工具、掩码和重复请求确定性的失败测试。
- [ ] 2.2 增加既有 `MCP` 调用和 CLI `/mcp tools` 完整清单的兼容性测试。
- [ ] 2.3 运行专项测试，再修正实现直到全部通过；不得改变 receipt/confirmation 行为。

## 3. 文档与验证

- [ ] 3.1 更新 MCP 使用文档与 threat-model，记录目录/详情边界和明确不做的能力。
- [ ] 3.2 补齐 design/plan/verification 证据，并运行全量 pytest、Ruff、格式检查、build 和 OpenSpec strict 校验。
- [ ] 3.3 最终进行两轮自评，检查模糊、错误、过度保守、前后不一致和遗漏；发现问题立即修复并复验。保持 PyPI 发布暂停。

```

## openspec/changes/mcp-progressive-disclosure/specs/mcp-progressive-disclosure/spec.md

- Source: openspec/changes/mcp-progressive-disclosure/specs/mcp-progressive-disclosure/spec.md
- Lines: 1-55
- SHA256: eb0bdfcb77fcefd6b114b479d87b1d92c2e6cd73be4220104408bb8a710055b2

```md
# mcp-progressive-disclosure Specification

## Purpose

定义 MCP 工具目录与按需详情的最小协议，降低 system prompt 的上下文成本，同时保持现有 MCP 调用安全边界。

## ADDED Requirements

### Requirement: MCP prompt uses a bounded tool directory

ForgeAgent SHALL inject only a bounded MCP directory into the task system prompt. Each advertised entry MUST use the manager-owned public server label, tool name, one-line bounded summary, and a permission hint; the prompt MUST identify descriptions as external data and MUST explain that `MCPDescribe` can provide details on demand. Full input schemas MUST NOT be injected into this directory.

#### Scenario: Directory lists available tools
- **WHEN** one or more MCP tools are available
- **THEN** the system prompt lists each public server/tool pair with a bounded summary and tells the model how to request details

#### Scenario: Long discovery metadata is bounded
- **WHEN** a server returns a very long or multiline description
- **THEN** the directory normalizes it to one line and truncates it within the configured summary limit

#### Scenario: No MCP tools are available
- **WHEN** no MCP tool is available
- **THEN** the MCP prompt section is empty and no `MCPDescribe` capability is advertised

### Requirement: MCPDescribe returns one safe tool detail

ForgeAgent SHALL expose a read-only `MCPDescribe` tool with arguments `{server, tool}`. It MUST read only the current available discovery snapshot, return a bounded masked description and JSON-like input schema, and MUST NOT connect to a server, execute an external action, request confirmation, or create an external-action receipt.

#### Scenario: Known tool is described
- **WHEN** `MCPDescribe` receives an available public server/tool pair
- **THEN** it returns the tool description, bounded input schema, and whether the call is auto-approved or requires confirmation

#### Scenario: Unknown tool is requested
- **WHEN** the server/tool pair is absent or unavailable
- **THEN** the tool returns a failed structured outcome with a bounded retry instruction and does not access the MCP loop

#### Scenario: Detail metadata exceeds limits
- **WHEN** the description or schema exceeds its configured bound or cannot be serialized safely
- **THEN** the result remains bounded and uses an empty schema or truncation continuation instead of exposing raw data

#### Scenario: Duplicate detail requests are deterministic
- **WHEN** the same `{server, tool}` is requested repeatedly without a discovery change
- **THEN** each response is derived from the same snapshot and no new network, connection, or side-effect operation occurs

### Requirement: Existing MCP calls and CLI diagnostics remain compatible

ForgeAgent SHALL keep the existing `MCP` ToolCall `{server, tool, arguments}` routing, confirmation, receipt, failure, and masking semantics unchanged. CLI `/mcp tools` MUST continue to display the complete available masked discovery listing, independent of the bounded system-prompt directory.

#### Scenario: Existing MCP call remains routable
- **WHEN** the model calls an advertised tool through `MCP`
- **THEN** the original server/tool identity reaches existing routing and the existing confirmation/receipt policy applies

#### Scenario: CLI requests full listing
- **WHEN** a user runs `/mcp tools`
- **THEN** the CLI displays the complete masked descriptions and schemas available from the manager

```

## openspec/changes/mcp-progressive-disclosure/specs/mcp-resilience/spec.md

- Source: openspec/changes/mcp-progressive-disclosure/specs/mcp-resilience/spec.md
- Lines: 1-30
- SHA256: 0009a7ce47d8336d62bdadd7a933e4cdff69c21656bcacd6ee85e0a188186733

```md
# mcp-resilience Specification Delta

## MODIFIED Requirements

### Requirement: MCP discovery metadata does not expose known secrets
ForgeAgent MUST apply the existing sensitive-environment value policy before discovered MCP metadata or configured server identity reaches the model prompt, CLI, ToolOutcome feedback, structured call errors, public status, required-startup diagnostics or lifecycle logs. JSON-like input schemas MUST be recursively masked; exact built-in floats MUST be finite, and any nested NaN, positive infinity or negative infinity MUST make the public schema `{}`; a masked key collision or any other non-JSON-like value MUST have the same result. A tool or configured server routing identity that contains a known secret MUST NOT be advertised because a masked display alias cannot be routed safely back to the original SDK identity. Public configured-server labels MUST be stable and collision-free; an unknown or manually supplied raw server identity MUST map to one manager-owned fixed category label allocated without collision against configured public labels and never derived from that raw input. Internal lifecycle, approval and call routing MUST continue to use the original identity. The bounded MCP directory and `MCPDescribe` detail projection MUST use the same masked public snapshot and MUST NOT introduce an alternate raw metadata path.

#### Scenario: Tool description contains a known secret
- **WHEN** MCP discovery returns a tool whose description contains a known sensitive environment value
- **THEN** the catalog, generated tools prompt, `MCPDescribe` detail and `/mcp` listing contain the redaction marker instead of the secret while preserving the safe tool name and its original call routing

#### Scenario: Input schema contains a known secret
- **WHEN** MCP discovery returns a JSON-like `inputSchema` whose keys or string values contain a known sensitive environment value
- **THEN** ForgeAgent recursively masks those keys and values before returning the catalog or `MCPDescribe` detail; if masking makes the schema structurally ambiguous or a non-JSON-like value is present, it returns an empty public schema instead of raw data

#### Scenario: Tool name contains a known secret
- **WHEN** MCP discovery returns a tool whose name would change under known-secret masking
- **THEN** ForgeAgent excludes that tool from the available catalog, directory and `MCPDescribe` lookup instead of advertising a non-routable masked alias

#### Scenario: Server identity contains a known secret
- **WHEN** a configured server identity would change under known-secret masking
- **THEN** ForgeAgent excludes that server's tools from the available catalog and directory, uses the same public label in status, required-startup, `/mcp`, `MCPDescribe`, ToolOutcome, structured error and lifecycle log output, and retains the original identity only for internal lifecycle, approval and call routing

#### Scenario: Redacted server labels collide
- **WHEN** two raw server identities mask to the same text or collide with an already-safe configured identity
- **THEN** ForgeAgent preserves every safe raw label, assigns deterministic non-secret numeric suffixes to the redacted identities, reports every status/failure without overwrite, and lets enable/disable feedback select the exact raw server's public label

#### Scenario: Manual or replayed MCP call contains a known secret
- **WHEN** a ToolCall supplies a secret-bearing server or tool identity even though it was not advertised
- **THEN** approval and call routing receive the raw identity while the next-round feedback and CLI outcome contain only the manager-owned public server label and masked tool label

```
