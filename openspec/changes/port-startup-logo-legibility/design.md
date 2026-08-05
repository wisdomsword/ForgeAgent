## 实现方案

- 以本地 main 的 M48 归档结果为基线，只移植旧分支 `bb5c780` 和 `cf3928a` 的生产代码与测试意图。
- 仅替换 `_STARTUP_LOGO` 五行常量；保留 `StartupDisplay` 的颜色、动画、`stop(persist=True)`、暂停/恢复及 `_logo_text()` 宽度降级逻辑。
- 完整 Logo 的最大行宽固定为 63 列；终端宽度 62 使用单行 `ForgeAgent`，宽度 63 保持五行字模。
- 归属基准是当前 main HEAD `54b3343`，不使用旧分支 `3245a448` 作为 diff 基准，也不移植旧分支的归档或文档对账提交。

## 验证策略

- 运行启动 Logo 聚焦测试和完整 `tests/test_cli.py`。
- 运行 Ruff format/check、OpenSpec strict 和 `git diff --check`。
- 复核改动文件只有 `_cli_repl.py`、`tests/test_cli.py` 及本 change 产物。
