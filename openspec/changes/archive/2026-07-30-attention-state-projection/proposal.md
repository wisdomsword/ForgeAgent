## Why

ForgeAgent 已能区分普通终态，但仍会把“等待用户或外部资源”的任务与失败任务混在一起。当前 `Survey` 只暴露 `needs_info`，Loop 和 HTTP 调用方没有稳定的 attention-state 契约，导致 headless 客户端无法判断应当补充输入、解除阻塞、重试还是按终态处理。

## What Changes

- 增加最小 attention-state 协议，将终态结果与可行动的注意力状态分离。
- 保留 `needs_info` 作为兼容输入，并映射为新的 `needs_input` attention state。
- 为 Loop 增加稳定的 `needs_input`、`blocked` stop reason，以及有界的 reason/detail/recovery 元数据。
- 通过 HTTP 任务提交和查询响应投影 attention state，但不暴露 prompt、工具参数或宿主数据。
- 保持取消、完成、失败和 `external_action_pending` 的既有语义不变。
- 增加确定性的单测、HTTP、Loop 和兼容性回归覆盖。

## Capabilities

### New Capabilities

- `attention-state-protocol`: Stable attention-state vocabulary, metadata, compatibility mapping, and public projection rules.

### Modified Capabilities

- `loop-execution`: Allow Loop reports to stop with `needs_input` or `blocked` and carry bounded attention metadata.
- `http-task-service`: Project attention state and recovery metadata for queued/running/terminal task views while preserving existing safe disclosure rules.

## Impact

- 运行时模块：按需修改 `src/forgeagent/step.py`、`src/forgeagent/task.py`、`src/forgeagent/loop.py`、`src/forgeagent/http_task_service.py` 和 `src/forgeagent/http_server.py`。
- 公共 JSON：新增 `attention` 对象和稳定的公开状态值；原有 `status`、`reason`、`detail` 字段继续保留。
- 不新增依赖、数据库、调度器、鉴权模式或发布动作。
- PyPI 发布、正式 tag、远程 push，以及 active 的 `publish-v0-1-0` change 均不在范围内并继续暂停。
