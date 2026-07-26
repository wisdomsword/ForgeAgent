## Why

M22 一键真实模型冒烟会继承用户全局 context feedback 限额。用户将 `tool_result_max_tokens` 设为 40、`round_feedback_max_tokens` 设为 120 时，Evaluator 只能看到约 147 字符的 `FileRead` 片段，即使生成文件和测试完全正确也会连续拒绝并以 `rejection_limit` 停止。

## What Changes

- M22 冒烟子进程使用固定的 2000/4000 取证预算，避免用户日常低预算造成假失败。
- 预算覆盖只作用于该子进程，不修改用户配置，不复制或回显 provider credential。
- 保留 Planner、FileWrite 等所有原生人工确认和真实模型路由行为。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `triad-human-smoke`: 明确一键冒烟必须隔离会破坏 Evaluator 取证的用户 context feedback 覆盖值。

## Impact

影响 M22 冒烟脚本、CLI 内部 context 配置加载缝和对应离线测试；不改变公开 CLI 参数、持久化 schema、模型注册表或依赖。
