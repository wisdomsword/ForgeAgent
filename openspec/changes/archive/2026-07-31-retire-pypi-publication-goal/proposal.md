## Why

M30 之后的里程碑已经完成运行时与治理能力，但规划文档仍把 PyPI、正式 tag、远程 push 和 `publish-v0-1-0` 保留为未来发布目标。这个残留会把历史 RC 事实误读为待办，也会让后续任务继续围绕一个已经撤销的外部交付目标排队。

## What Changes

- 将包索引发布、正式版本 tag、远程 push 和发布自动化从当前路线图中移除。
- 保留 M28 RC 的历史验证事实，但明确它不是当前发布计划，也不产生“待恢复授权”的后续任务。
- 将未完成的 `publish-v0-1-0` change 标记为已撤销并移出 active changes，保留其历史任务和取消原因。
- 统一 M30 及之后里程碑、ACTION_PLAN、借鉴清单、治理文档、发布说明和离线契约测试的分发边界表述。

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `agent-governance-gates`: 治理契约测试改为验证分发目标已移出路线图，而不是验证 PyPI 发布冻结和 active release change。
- `borrowing-review-baseline`: 规划基线记录分发目标已撤销，且不再要求保留 active `publish-v0-1-0`。
- `release-candidate-verification`: RC 文档改为历史工程验证记录，禁止把未执行的外部发布动作表达为未来门禁。

## Impact

- 仅修改项目内规划、规范、发布说明、里程碑台账和离线文档契约测试。
- 不修改 ForgeAgent 运行时代码、依赖、API 或测试运行时语义。
- 不访问网络、不上传包、不创建 tag、不 push，也不删除历史证据。
