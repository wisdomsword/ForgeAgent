## Why

ForgeAgent 当前只有 CLI 入口，无法被 cron、CI 或其他本地程序可靠触发；同时工具执行、模型调用和确认门缺少统一的可追溯记录。M16 在 M15 身份层之后补齐一个轻量的 headless HTTP 入口，并把审计留痕放在核心执行层，使 CLI 与 HTTP 共享同一安全和诊断语义。

## What Changes

- 新增异步任务 HTTP API：提交任务、查询状态与结果、取消任务。
- 新增静态 bearer token 鉴权、结构化错误响应和并发任务隔离。
- 新增核心层 JSONL 审计事件，覆盖工具执行、LLM 调用和确认门决策。
- 审计参数摘要复用现有 secret masking，并提供有界的按大小轮转配置。
- 将 HTTP headless 请求接入现有 non-TTY 确认门语义：gated tool 默认拒绝，可由显式 allowlist 预授权。
- 更新威胁模型、服务配置/运行文档和 M16 专项测试；保持既有 CLI 任务语义兼容。

## Capabilities

### New Capabilities

- `http-task-service`: 本地 headless HTTP 服务、任务生命周期 API、鉴权、并发和取消语义。
- `audit-logging`: 核心层 JSONL 审计事件模型、掩码、轮转和共享埋点语义。

### Modified Capabilities

- `tool-approval`: 明确 HTTP/non-TTY 路径的 gated tool 拒绝与显式预授权 allowlist 语义。

## Impact

- 代码：新增 HTTP 服务/任务仓库与审计模块；修改 `Task`/`Step`、工具注册表、LLM client、确认器和 CLI 装配。
- API：新增本地 HTTP 端点与 JSON 响应契约；既有 Python/CLI API 保持兼容。
- 配置：增加监听地址/端口、静态 bearer token、审计路径/轮转和 headless allowlist 配置。
- 测试：并发任务集成测试、HTTP golden 子集回放、逐字段审计断言、鉴权/取消/确认门边界测试。
- 文档与安全：更新 `README.md`、`docs/threat-model.md`，记录监听面、token 泄露、日志残留和本地绑定边界。
