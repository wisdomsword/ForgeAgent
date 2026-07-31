## Why

CollaborationRunner 当前把多数角色 Task 非完成原因压缩为 `role_failed`，并且没有完整表达资源耗尽、等待输入和阻塞语义；同时，角色执行所需的原始 goal 与公开 handoff goal 依赖同一构造路径，容易在修复路径泄漏时误伤合法执行意图。M39 需要在 Duo 验收契约变更前先稳定这一投影边界。

## What Changes

- 定义 Task 和 Loop 原因到 Collaboration `status`、`stop_reason`、`attention` 的完整确定性投影。
- 保留 `rejection_limit` 等正常停止原因，并透传 `max_rounds`、`wall_clock`、`token_budget`、`token_usage_unavailable` 等资源耗尽原因。
- 将 `needs_info` 投影为 `needs_input`，将 `blocked` 和未决外部动作投影为可恢复阻塞，而不是内部失败。
- 保持 auth/invalid-request、状态损坏和角色协议错误为失败终态，并继续屏蔽原始异常正文。
- 分离角色执行 goal 与公开 handoff goal：内部任务数据保留合法绝对路径，HandoffPacket、报告与审计只使用有界脱敏投影。
- 为公开报告增加兼容的 attention 投影，不移除既有 status/reason 字段。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `runtime-collaboration`：明确 Collaboration 终态原因和 attention 的来源映射。
- `structured-collaboration-handoff`：明确内部执行 goal 与公开 handoff/audit 投影的信任边界。

## Impact

影响 `src/forgeagent/collaboration.py` 及 Collaboration、Loop、HTTP、handoff 相关测试和规范。不新增依赖，不改变 single TaskOutcome，不执行 PyPI、tag、push 或发布自动化。
