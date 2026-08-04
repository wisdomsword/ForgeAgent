## 1. M47 回归基线

- [x] 1.1 在 `main` M47 基线上移植失败测试，要求符合条件的纯文本回答在一轮内以 `answered_in_prose` 结束，并先取得 RED。
- [x] 1.2 固定空响应、截断响应、工具/解析反馈、显式终态和 required completion tool 不进入 prose 软完成路径。

## 2. 最小行为移植

- [x] 2.1 对照旧 change 删除 M47 的一次性 `_PROSE_NUDGE` 路径和局部状态，保留 M47 后续的完成完整性与协作提交边界。
- [x] 2.2 移植真实 TTY 流式正文去重，保持非流式和其他结果渲染调用兼容。

## 3. 验证

- [ ] 3.1 运行 Step、Task、CLI、context、collaboration 聚焦测试、Ruff、全量测试和 OpenSpec strict 校验，审查没有重复执行或完成语义升级。
