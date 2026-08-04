## Why

`main` 的 M47 基线仍会在交互式初始化成功后清除 transient 启动 Logo，只保留启动摘要；旧分支已经验证了成功后保留一次稳定 Logo 的修复。M48 需要把该已验证行为单独移植到 M47，而不是合并旧分支或改写 `main` 已归档的 M46/M47。

## What Changes

- 从旧分支的 `2026-08-03-keep-startup-logo-visible` change 移植启动 Logo 持久显示行为，并按 M47 当前代码解决冲突。
- 保持启动动画为 transient；仅在交互式初始化成功结束时打印一次稳定静态 Logo，随后继续打印现有启动摘要。
- 保持确认暂停、启动失败、中断、非 TTY、`run` 和 `serve` 路径不持久显示 Logo。
- 移植并调整既有回归测试和 README 描述，验证 M47 基线没有行为退化。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `repl-startup-information`：交互式初始化成功后必须在终端保留恰好一个稳定 Logo。

## Impact

- 基线：`main` 的 M47；旧分支仅作为已验证补丁与测试来源，不整体合并。
- 代码：`src/forgeagent/_cli_repl.py` 的启动展示停止路径及调用点。
- 测试与文档：`tests/test_cli.py` 和 README 的交互式启动说明。
- 不新增依赖、配置或公共 API，不改动 `main` 的 M46/M47 归档含义。
