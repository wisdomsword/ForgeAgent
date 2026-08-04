## Why

`main` 的 M47 基线没有任务级 `RequestFilesystemAccess`，项目身份根、内置文件工具根和执行后端允许根仍无法在任务内独立升级；旧分支已经实现并验证了显式、一次性、任务级的全磁盘文件授权。M48 需要把该能力独立移植到 M47，同时保持默认 restricted 安全边界和 M47 后续变更。

## What Changes

- 从旧分支的 `2026-08-03-authorize-task-filesystem-access` change 移植任务级文件系统授权，并按 M47 当前代码解决冲突。
- 保持默认 sandbox tier 为 `restricted`，不静默降低安全默认值。
- 让显式 `trusted` tier 的 Exec 与内置文件工具具有一致的宿主文件系统访问范围。
- 为交互式 `restricted` 任务增加一次性全磁盘文件权限请求；批准后仅在当前 Task 内扩大文件访问范围，同时保留 restricted 的进程隔离、凭据清洗、资源限制和网络限制。
- 把实际 tier、当前文件权限范围和可用升级方式作为宿主事实注入模型上下文；MCP 调用批准不扩大 ForgeAgent 或 MCP server 的文件权限。
- `container` tier 不支持运行中扩大挂载范围，并返回明确、可恢复的拒绝结果。

## Capabilities

### New Capabilities

- `task-filesystem-authority`：定义 project root 与任务文件权限的分离、各 sandbox tier 的文件访问语义、任务级全磁盘授权生命周期，以及宿主权限事实投影。

### Modified Capabilities

- `tool-approval`：扩展类型安全确认接口，覆盖任务级全磁盘权限请求、一次决定语义、拒绝/无交互通道行为和最小披露审计。

## Impact

- 基线：`main` 的 M47；旧分支仅作为已验证补丁、spec 与测试来源，不整体合并。
- 影响 Task/Step 工具上下文、执行后端选择、运行时权限状态、CLI/REPL 确认提示和系统提示组合。
- 需要移植权限、工具、Task、CLI、身份提示和真实交互回归测试。
- 不增加依赖，不修改 HTTP 请求 schema，不持久化授权，不修改 MCP server 配置。
