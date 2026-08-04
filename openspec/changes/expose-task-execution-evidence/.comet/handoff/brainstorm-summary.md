# Brainstorm Summary

- Change: expose-task-execution-evidence
- Date: 2026-08-04

## 确认的技术方案

采用 Task 拥有的执行证据 recorder 与程序制品 store。`Step` 只在工具进入 dispatch 后记录尝试；`ExecTool` 在任何 backend dispatch 前把实际选中的代码原子写入项目根下 `.forgeagent/execution-artifacts/<execution-id>/programs/`，并把安全相对引用关联到该次尝试。模型提供的 `CodeBlock.path` 不参与宿主路径选择。

内部 Task 证据保留顺序、工具、稳定状态、可选 block 和程序引用；CLI 用项目根解析并显示本地路径，HTTP 只投影 `execution-artifacts/...` 形式的 canonical relative POSIX 引用。Loop checkpoint 与 Collaboration state 持久化带 iteration、role、attempt 来源的有界安全聚合，恢复后继续去重追加。

HTTP 本 change 只返回相对引用，不新增下载端点。HTTP 测试通过内部项目根解析证明引用对应已持久化文件，并验证公开 JSON 不含绝对路径；引用只承诺在 terminal record 可查询期间作为结果元数据稳定，不承诺可通过 HTTP 解引用。

容量固定为：每个 Task 最多 100 个程序制品，单文件最多 1 MiB、Task 总量最多 8 MiB；内部最多保留 128 条工具尝试，CLI/HTTP/Loop/Collaboration 每次公开投影最多 32 条并携带显式 omitted/truncated 信息。标签和引用分别执行固定字符上限、控制字符清理与 secret masking。

程序目录使用 host-generated UUID 命名空间，目录权限 0700、文件权限 0600；目录遍历和原子发布使用 directory descriptor、`O_NOFOLLOW`、临时文件、`fsync` 和 `os.replace`，目录 symlink/rebinding 或容量失败都返回稳定 artifact-persistence failure，且不得执行代码。

制品在 M48 中持久保留，由项目/宿主运维者负责清理；Task.close、HTTP record 过期、Loop/Collaboration close 均不删除已公开路径。本 change 不增加自动 GC、下载服务或全局配额。

## 关键取舍与风险

- 未采用终态扫描 rounds：它不能自然覆盖 durable aggregate 状态，且容易把 parsed-but-skipped tool 误当作 attempted。
- 未复用 audit log：审计 sink 可以降级，且其保留/敏感信息契约与用户终态结果不同。
- fail-closed 会让制品目录不可用时原本可执行的 Exec 失败；这是“执行过的程序必有路径”契约的必要代价。
- 不做自动清理避免 Task.close 后路径立即失效，但跨任务磁盘增长留给后续独立生命周期能力处理；本 change 通过单 Task 上限控制局部风险。
- Loop/Collaboration 的持久聚合只保存安全相对引用，不保存宿主绝对路径；CLI 在当前项目根下解析显示本地路径。

## 测试策略

先写失败测试，再实现：程序 store 的权限、原子写入、symlink/rebinding、大小/数量/总量与 backend 未调用；命名/内联 Exec 在 trusted/restricted/container 的制品一致性；parsed-but-skipped、成功/失败、prose 空集合和 cancellation 保留；CLI/REPL 单次终态本地路径；HTTP terminal 空/非空安全投影；Loop checkpoint 与 Collaboration state 的 iteration/role/attempt 聚合、截断、恢复和去重；旧 checkpoint/state 默认空证据兼容。最后运行受影响面、Ruff、OpenSpec strict 和全量 pytest。

## Spec Patch

- 为 task-execution-evidence 增加容量超限与 artifact 目录 symlink/rebinding 的 fail-closed 场景。
- 明确公开投影的固定上限、显式 omitted 计数和来源字段。
- 明确 HTTP 只提供相对引用、不提供下载端点，并要求内部引用能对应已持久化程序文件。
- 明确 Task/HTTP record/Loop/Collaboration close 不删除已公开制品，M48 不实现自动 GC。
