## 1. M47 回归基线

- [x] 1.1 在 `main` M47 基线上移植启动展示失败测试，证明确认暂停不残留静态 Logo、成功停止后仅保留一次稳定 Logo，并先取得 RED。

## 2. 最小行为移植

- [x] 2.1 对照旧 change 移植 `StartupDisplay.stop(persist=...)` 与唯一成功调用点，处理 M47 冲突且不覆盖相邻启动行为。
- [x] 2.2 更新 README 的最终可见状态说明，并确认非 TTY、失败、中断、`run`、`serve` 行为不变。

## 3. 验证

- [ ] 3.1 运行 CLI 聚焦测试、Ruff、全量测试和 OpenSpec strict 校验，审查最终差异仅包含本移植能力。
