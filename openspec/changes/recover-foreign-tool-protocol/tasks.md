## 1. 回归测试

- [x] 1.1 为独立 `cmd` JSON、`todo_write` + `Params:`、fenced 示例和普通 prose 增加 parser/Step/Task RED 测试，并确认失败原因是外部工具文本仍被软完成。

## 2. 最小修复

- [x] 2.1 在文本协议解析边界增加结构化外部工具形态检测，复用现有 ParseError 反馈环且不执行裸命令。

## 3. 验证与收尾

- [x] 3.1 运行聚焦、相关、完整回归、Ruff、build、OpenSpec strict 与真实 CLI smoke，并为 verify 阶段保留完整证据。
