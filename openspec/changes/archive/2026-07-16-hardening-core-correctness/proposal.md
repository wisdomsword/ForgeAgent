## Why

本次 CodeGraph、静态检查和测试评审发现 ForgeAgent 在网络边界、工具确认、任务完成判定和 MCP 生命周期上存在可被触发的正确性或安全风险；同时，现有黄金任务目录不能产生可重复的自动验证证据。现在需要把这些问题收敛为一个可设计、可实施、可验收的加固里程碑，避免安全修复与验证口径继续分离。

## What Changes

- 默认禁用环境代理对 WebFetch 和 `/search` 的影响，确保 SSRF 校验针对实际直连目标；仅记录 ForgeAgent 显式代理配置契约，本里程碑不实现代理功能。
- WebFetch artifact 与文件工具统一使用 canonical root containment，阻断预置 artifact symlink 指向 `allowed_root` 外部目标，同时明确保留 hostile target/ancestor component swap 的 TOCTOU 残余威胁。
- 为 WebFetch、FileWrite、MCP 统一确认器；TTY 自动询问，非 TTY 默认拒绝，`--interactive` 继续只控制 Survey。
- 收口 CLI 交互契约：非 TTY REPL 不读取确认输入；MCP 标识和 FileWrite 展示路径同样脱敏并按单行 literal text 渲染，模型字符串不能注入 Rich markup、终端控制换行、Unicode 双向/格式控制或不可编码 surrogate；移除 M9 已到期的 REPL 裸词命令兼容层，仅 slash command 参与内嵌路由。
- 采用严格两阶段完成语义：含工具调用、工具失败或解析错误的响应不得完成任务；只有后续无工具、无解析错误的独立响应才可声明完成。
- 增加 MCP 服务级 `required` 配置；可选服务失败时降级，必需服务失败时 CLI 以非零状态启动失败；关闭流程有界、幂等且不覆盖原任务结果。
- 隔离测试 HOME 和 MCP 配置，避免测试读取用户机器上的真实配置。
- 建立 20 个完全离线、可执行、自动判定并生成报告的黄金验证核心，其中 5 个场景支持可选真实模型运行；其余目录项明确标记为候选而非已验证。
- 同步模型客户端、文本协议、威胁模型、黄金任务、README 和里程碑文档，消除实现与文档契约漂移。

## Capabilities

### New Capabilities

- `network-boundary-safety`: 规定 WebFetch 和搜索请求的代理、目标地址、重定向和逐跳 SSRF 边界。
- `tool-approval`: 规定 WebFetch、FileWrite、MCP 的统一确认接口、TTY 行为、非交互拒绝策略和 REPL 内嵌命令路由收口。
- `completion-integrity`: 规定工具调用、工具结果、解析错误与 `task_status.completed` 之间的完成状态转换。
- `mcp-resilience`: 规定 MCP 服务的 `required` 启动策略、降级行为和关闭生命周期保证。
- `golden-validation-core`: 规定离线黄金场景 manifest、fixture、自动判定、报告和可选真实模型运行边界。

### Modified Capabilities

无。当前仓库不存在可修改的既有 OpenSpec capability spec；协议和文档同步将在实现与验证任务中完成。

## Impact

- 影响 `src/forgeagent/ssrf_guard.py`、`src/forgeagent/cli.py`、`src/forgeagent/step.py`、`src/forgeagent/mcp_manager.py`、`src/forgeagent/tools.py`、`src/forgeagent/web_search.py`、`src/forgeagent/_sandbox_worker.py` 及其调用方。
- 新增或调整 MCP 配置字段、工具确认器接口和任务完成状态判定，属于用户可观察行为契约变化。
- 扩展测试 fixtures、隔离环境、黄金任务 runner 和报告产物；Agent-loop 场景使用 MockClient，边界场景可直接调用对应本地入口；基础 CI 保持完全离线，不依赖供应商 API key、Docker 或外部网络。
- 更新相关 `docs/`、README、里程碑和威胁模型文档；不修改 `resource/agent/`，不引入厂商专用端点或凭证。
