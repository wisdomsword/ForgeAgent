## Why

M18 人工复测发现，模型在工具自纠错的多个 round 中重复发出同一个 Memory 标记时，
Task 会重复应用并展示相同准入结果；同次复测还证明固定协议给出的
`utils.set_state(key=value)` 示例与真实位置参数 API 不一致，诱发了不必要的 Exec 失败。

## What Changes

- 让单个 Task 内完全相同的 Memory 候选具有幂等语义，只应用并反馈一次。
- 保留同 key 不同内容候选的原有出现顺序和后写覆盖语义。
- 更正固定协议中的 `utils` 调用方式，并明确纯记忆请求无需 Exec。
- 增加重复候选与固定协议文本的回归测试。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `runtime-memory`：明确单 Task 内完全相同的模型候选只处理一次，避免重复写入、审计和 CLI 反馈。
- `runtime-identity`：更正固定协议公开的 `utils` 注入方式和精确调用签名，并明确纯记忆请求无需 Exec。

## Impact

影响 `src/forgeagent/task.py`、`src/forgeagent/res/prompts/protocol.md` 及对应测试；不改变
MemoryCandidate/MemoryResult public shape、持久化格式、HTTP schema 或依赖。
