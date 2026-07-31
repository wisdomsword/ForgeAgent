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
