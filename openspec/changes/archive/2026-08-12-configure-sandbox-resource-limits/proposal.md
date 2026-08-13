## Why

restricted 的 30 秒 wall timeout、10 秒 CPU 和 512 MiB memory 全部硬编码，CLI 与配置无法按任务规模调整；rlimit 终止只返回裸信号号并丢失终止前输出。

## What Changes

- 新增 restricted 专用限制对象，支持配置文件和 CLI 覆盖，优先级为 CLI > 配置 > 默认值。
- 将 CPU 信号翻译为稳定的人类可读原因，SIGKILL 保持非过度断言。
- 用有界父进程可见通道保留信号/超时前已产生的 stdout/stderr，并在反馈前掩码。

## Capabilities

### Modified Capabilities

- `task-filesystem-authority`：restricted 资源限额可配置且反馈可诊断。

## Impact

- Task、CLI、HTTP runtime、restricted executor/worker 及对应测试。
- 不改变 container 配置，不新增依赖。
