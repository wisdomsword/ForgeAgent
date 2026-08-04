## Why

ForgeAgent 目前只在轮次内返回工具结果：`ToolOutcome` 和 `StoredBlock` 没有程序制品路径，解析得到的 `CodeBlock.path` 在存储时丢失，内联 Exec 及 restricted/container 执行也只通过内存或 stdin 传递代码。用户因此无法在任务终态确认 ForgeAgent 使用了哪些工具、工具是否成功，以及实际执行的生成程序位于何处。

## What Changes

- 为 M48 新增任务级执行证据契约，记录实际尝试的工具、稳定状态和关联程序制品，不暴露原始参数、凭据、prompt 或文件内容。
- 将所有实际执行的生成代码（包括命名代码块和内联 Exec）持久化到任务级制品目录，并为每次执行关联稳定制品引用。
- CLI 在任务终态汇总工具、状态和本地程序路径；纯 prose 且未调用工具时明确显示没有工具或程序执行。
- HTTP 只返回安全、相对的制品引用，禁止暴露宿主绝对路径；投影保持有界、脱敏且兼容既有字段。
- Loop、Duo、Triad 在终态聚合内部任务的有界执行证据；失败、停止和取消也保留已经尝试的证据。
- 终态汇总一次性输出，不在每轮重复刷屏。

## Capabilities

### New Capabilities

- `task-execution-evidence`：定义任务级工具尝试、稳定状态、程序制品持久化、入口投影和敏感信息边界。

### Modified Capabilities

- `http-task-service`：终态公开结果增加有界工具证据和安全相对制品引用，同时继续禁止宿主绝对路径。
- `loop-execution`：Loop 终态报告聚合各次任务已经尝试的有界执行证据。
- `runtime-collaboration`：Duo/Triad 终态报告聚合各角色已经尝试的有界执行证据。

## Impact

- 影响 protocol/block store、Exec 工具与 executor 边界、Task/Step 结果模型、CLI 渲染、HTTP public view、Loop 和 collaboration 报告。
- 新增任务级程序制品持久化与引用契约，但不新增外部依赖。
- 需要定义制品目录、命名、保留、失败写入和边界投影策略，并覆盖 single/HTTP/Loop/Duo/Triad。
- 不输出原始工具参数、凭据、完整 prompt、任意文件内容或 HTTP 宿主绝对路径；不逐轮增加终端噪声。
