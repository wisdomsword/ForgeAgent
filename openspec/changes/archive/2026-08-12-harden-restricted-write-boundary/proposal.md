## Why

默认 `restricted` worker 会为导入保留 `sys.base_prefix` / `sys.prefix` 的读访问，但当前实现把这些前缀也放进了写路径白名单。结果是任务代码可以把文件写进虚拟环境的 `site-packages`，再用 `.pth` 或直接覆盖模块在后续 `python -I` 启动时提前执行，绕过 audit hook、rlimit、网络禁令和环境清洗边界。

## What Changes

- 让 restricted worker 仅对 `allowed_root` 保留写权限；Python 运行时前缀继续可读以支持正常导入，但不可写。
- 增加真实 restricted 子进程回归，覆盖 runtime prefix 普通写入、`.pth` 写入和 worker 自身文件写入三条逃逸路径。
- 更新 threat model，明确 `-I` 仍允许已安装环境的 `site-packages` 参与导入，但 restricted 边界禁止任务代码向这些前缀写入。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `tool-approval`：restricted worker 的可信安装/导入前缀只用于读，不得作为任务代码写入目标或持久化逃逸载体。

## Impact

- 代码：`src/forgeagent/_sandbox_worker.py`。
- 测试：`tests/test_restricted_backend.py`。
- 文档：`docs/threat-model.md`。
- 不修改公共 API、配置面、container tier 或任务级文件授权行为。
