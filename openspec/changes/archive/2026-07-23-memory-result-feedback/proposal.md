## Why

M18 人工验收证明 `--no-memory` 正确阻止了写入，但模型候选的
`MemoryResult(status="disabled")` 被 `Task.run()` 丢弃，CLI 因而只展示模型“已记住”的
口头声明，没有展示运行时的真实拒绝结果。这与既有 runtime-memory 规格要求的结构化拒绝
反馈和归档任务“暴露处理结果”不一致。

同次验收还发现 REPL 在输入提示符按 `Ctrl-C` 会泄漏 traceback，而不是正常退出。

## What Changes

- 保留并展示已完成任务产生的 MemoryResult，不触发额外模型调用，也不改变任务完成语义。
- 在 REPL 输入提示符捕获 KeyboardInterrupt，关闭资源后安静退出。
- 增加 `--no-memory` 模型候选反馈和 Ctrl-C 退出回归测试。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `runtime-memory`：明确模型候选的准入结果必须由 Task 暴露，并由 CLI 展示权威运行时结果；
  这是对既有拒绝反馈契约的可测试化。

## Impact

影响 `src/forgeagent/task.py`、`src/forgeagent/cli.py` 及对应测试；不改变 HTTP 请求/响应
schema，不增加依赖，不修改记忆准入规则或持久化格式。
