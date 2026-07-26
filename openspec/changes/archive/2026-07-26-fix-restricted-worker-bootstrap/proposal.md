## Why

默认 `restricted` 执行器使用 `python -m forgeagent._sandbox_worker` 启动安全 worker。Python 默认会把当前工作目录放在模块搜索路径前部，因此任务目录中的伪造 `forgeagent/_sandbox_worker.py` 可以在真实 audit hook 安装前被执行，绕过 restricted 边界。

## What Changes

- 以 Python isolated mode 启动 restricted worker，使当前工作目录和用户级 Python 路径不能覆盖已安装的 ForgeAgent worker。
- 增加真实子进程回归，证明 `allowed_root` 中的伪造 worker 和 runtime 模块不会被加载。
- 更新安全合同和威胁模型，明确 worker bootstrap 属于 restricted 边界的一部分。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `tool-approval`: restricted worker 必须从可信安装位置启动，不得从 `allowed_root` 解析同名 ForgeAgent 模块。

## Impact

- 代码：`src/forgeagent/executor.py`。
- 测试：`tests/test_restricted_backend.py`。
- 文档：`docs/threat-model.md`。
- 不修改公共 API、协议、配置、依赖或 container worker 的既有启动方式。
