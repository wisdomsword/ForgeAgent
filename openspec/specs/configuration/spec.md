# configuration Specification

## Purpose
定义模型、provider 与 MCP 配置在合并前的严格结构校验，以及生成参数的有限数值约束。
## Requirements
### Requirement: 模型与 provider 配置采用显式结构
ForgeAgent MUST 在合并内建和用户 YAML 前，逐份验证 models.yaml 与 config.yaml 的根节点是 mapping。models.yaml 仅允许 `default_model` 与 `models`；共享 config.yaml 仅允许既有的 `groups`、`context`、`restricted` 与 `search_engine`。ModelEntry、GroupConfig 与 Registry MUST 拒绝未知字段。

#### Scenario: 拼错顶层键时拒绝启动
- **WHEN** 任一 models.yaml 或 config.yaml 使用未知顶层键
- **THEN** ForgeAgent MUST 以包含该 YAML 来源的稳定 `invalid configuration` 错误拒绝加载
- **AND THEN** 不得静默忽略该键或暴露完整 Pydantic 诊断

#### Scenario: YAML 根节点不是 mapping
- **WHEN** 任一模型或 provider YAML 的根节点是列表、标量或其他非 mapping 值
- **THEN** ForgeAgent MUST 以包含该 YAML 来源的稳定 `invalid configuration` 错误拒绝加载

#### Scenario: 共享配置段共存
- **WHEN** 用户 config.yaml 同时包含合法的 `groups`、`context`、`restricted` 与 `search_engine`
- **THEN** registry 加载 MUST 接受该文件并只消费自身负责的 provider 与 sandbox 字段
- **AND THEN** 不得因其它既有共享配置段而拒绝启动

### Requirement: MCP 配置启停字段不得隐式转换
ForgeAgent MUST 在合并前逐份验证 mcp.yaml 根节点为 mapping，且唯一允许的顶层键为 `mcpServers`；其值必须是 mapping。MCPServerConfig MUST 拒绝未知字段，且 `enabled` 与 `required` MUST 仅接受 YAML 布尔值。

#### Scenario: MCP 布尔字符串不能启用服务器
- **WHEN** MCP server entry 将 `enabled` 或 `required` 配为字符串或数字
- **THEN** ForgeAgent MUST 拒绝加载该配置并报告包含 mcp.yaml 来源的稳定 `invalid configuration` 错误
- **AND THEN** 不得启动该 MCP server

#### Scenario: 保留 autoApprove 别名
- **WHEN** 合法 MCP entry 使用 `autoApprove`
- **THEN** ForgeAgent MUST 将其解析为 `auto_approve`，且不影响现有配置兼容性

### Requirement: 生成温度必须是有限数
ForgeAgent MUST 拒绝 GenerationParams.temperature 的 NaN、正无穷和负无穷，同时保留任何有限浮点数的现有行为。

#### Scenario: temperature 为 NaN
- **WHEN** 调用方以 NaN 设置 temperature
- **THEN** GenerationParams 验证 MUST 失败
