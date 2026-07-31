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

`MCPToolInfo` 在 discovery 阶段已完成 masking，因此目录和详情都只使用 public projection。所有新增文本使用现有 `ToolOutcome` bounded feedback；重复请求从同一快照生成确定性结果，不发起网络或连接操作。CLI `/mcp tools` 直接读取 `list_tools()`，继续显示完整 masked 描述和既有诊断字段；schema 不因 system prompt 变更而丢失，只改为由详情工具按需返回。

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
