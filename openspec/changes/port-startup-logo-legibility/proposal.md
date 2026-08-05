## Why

当前 main 的启动 Logo 使用压缩的混合大小写字模，`A` 和末尾 `T` 不易辨认，产品标识在真实终端中缺少稳定的可读性。旧分支已经用纯 ASCII 大写字模和边界测试验证了一个最小修正，应独立移植到 M48 之后的 main。

## What Changes

- 将 `_STARTUP_LOGO` 替换为五行、纯 ASCII、最多 63 列的 `FORGEAGENT` 大写字模。
- 增加完整字模、ASCII 约束以及 62/63 列窄终端选择边界的回归测试。
- 保持现有动画、颜色循环、成功后持久显示、确认暂停和 `ForgeAgent` 单行降级行为不变。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。现有 `repl-startup-information` 的纯 ASCII 产品标识契约不变，本 change 只改进其具体字形的可读性。

## Impact

- 修改 `src/forgeagent/_cli_repl.py` 中的私有 `_STARTUP_LOGO` 常量。
- 修改 `tests/test_cli.py` 中的启动 Logo 回归测试。
- 不新增依赖、配置、公共 API、持久化行为或终端能力判定。
