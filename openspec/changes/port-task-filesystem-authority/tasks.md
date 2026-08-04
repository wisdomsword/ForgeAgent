## 1. M47 安全回归基线

- [x] 1.1 在 `main` M47 基线上移植 `RequestFilesystemAccess` 协议、默认注册、单行脱敏确认及无交互/拒绝的失败测试，并先取得 RED。
- [x] 1.2 对照 M47 当前 `tool-approval` 契约识别冲突，确保不覆盖 M47 的 HTTP、receipt 或确认安全增强。

## 2. 权限工具与任务状态移植

- [x] 2.1 移植类型安全权限请求、一次性 Task 决定缓存和最小披露审计，保持 trusted/container 固定边界。
- [x] 2.2 移植 project root 与 filesystem root 分离、restricted 批准后的 backend 切换，以及 trusted Exec/内置文件工具权限一致性。

## 3. 宿主事实与入口回归

- [x] 3.1 移植 host-generated Runtime Authority，覆盖默认/自定义 prompt、restricted/trusted/container、custom registry/backend 和 MCP 非升级说明。
- [x] 3.2 移植 CLI/REPL 端到端回归，证明单 Task 只确认一次、新 goal 恢复 project scope、无确认通道 fail closed。

## 4. 验证

- [x] 4.1 运行权限/工具/Task/CLI 聚焦测试、Ruff、全量测试和 OpenSpec strict 校验，并审查最终差异没有权限扩大或无关旧分支内容。
