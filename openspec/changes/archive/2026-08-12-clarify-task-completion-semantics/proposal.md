## Why

Task 机器结果把无工具的 prose 回答记录为 `completed=False`，但 CLI 同时显示 `completed (answered in prose, not executed)`。这会让人类界面与机器投影对同一执行得出相反结论，并模糊“已经过 code-as-action 验证”和“模型仅给出未经执行的回答”之间的边界。

## What Changes

- 引入 `verified_completed`、`answered_unverified`、`stopped` 三态完成语义。
- 保留 `completed: bool` 作为 verified-only 兼容投影，并兼容现有构造调用。
- CLI、HTTP 与 audit 公开一致三态；Loop、evaluation 和 golden 继续使用 verified-only 布尔投影。
- 禁止构造 `completed=True` 但 reason 为 prose/停止原因的矛盾状态。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `completion-integrity`：任务终态必须区分已验证完成、未经验证 prose 回答和停止，所有公开投影不得相互矛盾。

## Impact

- 运行时：`src/forgeagent/task.py`、`src/forgeagent/cli.py`、`src/forgeagent/http_task_service.py`。
- 测试：Task、CLI、HTTP 与 audit 契约。
- 不把 prose 回答升级为 verified completion，不改变 Loop/evaluation/golden 的通过判定。
