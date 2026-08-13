## ADDED Requirements

### Requirement: 运行时内部拆分保留公共门面兼容
ForgeAgent MAY 将纯解析、数据类型、配置加载与路由决策移动到内部模块，但原有公共模块 MUST 继续提供既有导入路径和支持的猴子补丁位置。状态机、持久化、IO、工具派发和生命周期所有权 MUST 留在原有权威模块，除非后续独立 change 明确修改该契约。

#### Scenario: 调用方继续使用旧导入路径
- **WHEN** 调用方从 `forgeagent.protocol`、`forgeagent.step`、`forgeagent.mcp_manager` 或 `forgeagent.collaboration` 导入既有公开对象
- **THEN** 导入和运行时行为 MUST 与拆分前兼容

#### Scenario: 测试替换 MCP 门面默认路径
- **WHEN** 测试猴子补丁 `forgeagent.mcp_manager.DEFAULT_USER_MCP_PATH` 后无参调用 `load_mcp_config`
- **THEN** 加载器 MUST 使用被替换的门面路径

#### Scenario: 审查内部所有权
- **WHEN** 维护者检查新内部模块
- **THEN** 它们 MUST NOT 引入通用 manager、factory、framework 或新的运行时依赖
- **AND THEN** C901 结果只作为报告基线，不得在本 change 中成为阻断门禁
