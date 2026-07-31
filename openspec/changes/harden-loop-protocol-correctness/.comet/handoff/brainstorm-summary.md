# Brainstorm Summary

- Change: harden-loop-protocol-correctness
- Date: 2026-07-31

## 确认的技术方案

- LoopCheckpoint/LoopReport 使用 `schema_` + `alias="schema"` + alias 序列化，保持旧 JSON。
- parser 在 dispatch 前按显式 tool-call ID 合并双通道；等价重复保留一次，冲突 ID 记录 parse error 且不执行。
- `_safe_text` 抽为一个内部 helper，调用方显式保留空值策略。
- continuation 常量改为 English-first；`_apply_edit` 只从 `tools` 暴露。
- capability/receipt projection 失败只记录稳定事件名和异常类型。

## 关键取舍与风险

- 不改变 M27 缺失 collaboration source 的迁移语义。
- 不对缺失 ID 的调用做启发式去重。
- 不在本 change 结构化 Loop handoff 或扩展协作终态映射。

## 测试策略

覆盖旧 checkpoint/report JSON、双通道同 ID 等价/冲突/独立调用、空 prose、三处 `_safe_text` 行为、英文 continuation、私有导入和不泄漏日志；再运行相关 pytest、ruff、format、OpenSpec strict。

## Spec Patch

已写入本 change 的三份 delta spec：`loop-execution`、`completion-integrity`、`tool-call-identity`。
