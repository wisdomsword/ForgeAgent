## 1. Loop 模型兼容性

- [x] 1.1 将 `LoopCheckpoint` 和 `LoopReport` 改为正式 `schema_` alias 字段，并增加 `schema` 序列化和旧 JSON 加载测试。
- [x] 1.2 增加旧 checkpoint/report 回归断言，确认 M27 collaboration-source 迁移语义不变。

## 2. 协议身份与完成语义

- [x] 2.1 按显式 ID 实现 text/native 双通道工具调用的确定性去重。
- [x] 2.2 对冲突重复 ID 生成有界 parse error，并确保不分发该 ID。
- [x] 2.3 增加空正文和空白正文的 prose 完成回归测试。

## 3. 共享安全与反馈

- [x] 3.1 提取共享 `_safe_text`，迁移 loop、collaboration、external-action 调用方且不改变语义。
- [x] 3.2 将模型可见 continuation 常量改为 English-first 有界文本并更新 focused tests。

## 4. 所有权与可观测性

- [x] 4.1 移除 `step` 对私有 `_apply_edit` 的再导出，更新历史测试从 `tools` 导入。
- [x] 4.2 为 capability/receipt projection fallback 增加固定类型 warning 日志，不泄漏原始异常或 secret。
- [x] 4.3 运行 focused tests、format、lint、OpenSpec strict，并记录仅由环境导致的全量测试失败。全量回归曾出现 3 项代码回归，已修复并由 316 项 focused tests 覆盖；后续全量验证重新执行。
