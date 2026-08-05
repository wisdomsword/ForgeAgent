## 1. 字模与回归测试

- [x] 1.1 为完整 Logo 添加精确文本、纯 ASCII 和最大宽度 63 列断言。
- [x] 1.2 添加 62/63 列终端边界测试，确认紧凑单行降级和完整五行字模选择稳定。

## 2. 实现与验证

- [x] 2.1 将 `_STARTUP_LOGO` 替换为可读的大写纯 ASCII 字模，保持启动生命周期行为不变。
- [x] 2.2 运行聚焦/完整测试、Ruff、OpenSpec strict 和 diff 检查，完成代码提交。
- [x] 2.3 对齐 proposal、design 与 `repl-startup-information` delta，并重新通过 OpenSpec strict。
