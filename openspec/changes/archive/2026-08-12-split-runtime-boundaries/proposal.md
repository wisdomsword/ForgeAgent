## Why

protocol、step、mcp_manager 与 collaboration 的超大文件提高审查和修改风险，但行为契约必须在安全修复与存储准入后冻结才能移动。

## What Changes

- 抽取 protocol 的纯文本扫描阶段、Step 的纯数据类型/历史投影、MCP 严格配置加载、collaboration 纯路由决策。
- 原模块保持公共 facade 和重导出，状态机、IO、工具派发与生命周期所有权不变。
- C901 仅报告，不新增阻塞门禁。

## Capabilities

### Modified Capabilities

- `repository-lifecycle-integrity`：内部模块移动必须保留既有公共导入路径、门面猴子补丁位置和运行时所有权。

## Impact

- 新增四个小型内部模块，原调用方导入路径不变。
- 不新增 manager/factory/framework，不改变运行时能力。
