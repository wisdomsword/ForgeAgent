## Why

模型注册与 MCP 配置目前会静默忽略未知根键或叶字段；MCP 的 `enabled` / `required` 还会把字符串和数字强制转换为布尔值。用户拼错禁用字段时，原本不应启动的 MCP 进程会照常启动。另有 YAML 根节点为非 mapping 时的属性错误，以及 temperature 接受 NaN/无穷大的输入缺口。

## What Changes

- 每份 models、共享 config、MCP YAML 在合并前校验根节点是 mapping 且只有该文件允许的顶层键；共享 config 保留既有的 `groups`、`context`、`restricted` 与 `search_engine`。
- ModelEntry、GroupConfig、Registry、MCPServerConfig 拒绝未知叶字段。
- MCP 仅将 `enabled` 和 `required` 收紧为严格布尔值；其他既有字段的兼容转换保持不变。
- temperature 改为有限浮点数，不新增厂商范围限制。
- 配置失败统一返回包含配置来源的稳定启动错误，不向调用方展开 Pydantic 原始诊断。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `configuration`：配置文件必须有明确结构；未知配置不再被忽略或隐式转换。

## Impact

- 修改模型注册、MCP 配置加载与公共生成参数验证。
- 既有合法 aliases、`autoApprove` 别名和 user-over-builtin 覆盖语义保持不变。
