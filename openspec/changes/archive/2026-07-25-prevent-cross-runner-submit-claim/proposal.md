## Why

多个 `CollaborationRunner` 从同一 revision 并发恢复时，loser 的 Submit 会因 CAS 失败，但 Runner
仅凭共享状态已前进就会把 winner 的提交误认成自己的提交，并随后将合法协作写成终态失败。
同时，两个 Store 首次并发初始化同一目录时存在 `lstat`/`mkdir` 竞态，可能泄漏原始
`FileExistsError`。

## What Changes

- Runner 只有在本次 `TaskOutcome` 含成功的 required Submit outcome 时，才认领对应持久化边界。
- Submit loser 检测到共享 revision 已被其他 Runner 推进时，只返回本地 `state_failure`，不得写终态、
  递增 attempt 或补记统计。
- Store 首次并发初始化复用另一实例刚创建并通过安全校验的目录。
- 增加 Planner、Generator、Evaluator 的提交归属回归测试，以及首次并发初始化测试。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。修复落实现有 revision CAS、原子提交和恢复约束，不改变公开行为契约。

## Impact

- 代码：`src/forgeagent/collaboration.py`
- 测试：`tests/test_collaboration_store.py`、`tests/test_collaboration_runner.py`、
  `tests/test_collaboration_planner.py`
- 公开 API、依赖和持久化 schema：不变
