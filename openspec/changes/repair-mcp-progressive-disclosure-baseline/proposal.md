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
